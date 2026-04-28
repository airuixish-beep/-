from decimal import Decimal, InvalidOperation

from django.utils import timezone

from payments.models import Payment

from .models import RiskAssessment, Transaction

HIGH_AMOUNT_THRESHOLD = Decimal("300.00")
FAILED_ATTEMPT_LOOKBACK_HOURS = 24
FAILED_ATTEMPT_REVIEW_THRESHOLD = 2
RETRY_ATTEMPT_REVIEW_THRESHOLD = 2
RISK_STATUS_PRIORITY = {
    Transaction.RiskStatus.NONE: 0,
    RiskAssessment.Decision.ALLOW: 1,
    RiskAssessment.Decision.REVIEW: 2,
    RiskAssessment.Decision.BLOCK: 3,
}


class RiskService:
    @staticmethod
    def _parse_amount(payload):
        try:
            return Decimal(str((payload or {}).get("amount", "0")))
        except (InvalidOperation, TypeError):
            return Decimal("0.00")

    @staticmethod
    def _build_triggered_rule(code, label, score, details):
        return {
            "code": code,
            "label": label,
            "score": score,
            "details": details,
        }

    @classmethod
    def evaluate(cls, transaction_obj, *, payload=None):
        payload = payload or {}
        triggered_rules = []
        score = 0
        amount = cls._parse_amount(payload)
        phase = payload.get("phase", "")
        customer_email = (payload.get("customer_email") or "").strip()

        if amount >= HIGH_AMOUNT_THRESHOLD:
            rule_score = 40
            score += rule_score
            triggered_rules.append(
                cls._build_triggered_rule(
                    "high_amount",
                    "高金额订单",
                    rule_score,
                    {
                        "amount": str(amount),
                        "threshold": str(HIGH_AMOUNT_THRESHOLD),
                    },
                )
            )

        if payload.get("is_retry") or phase == "pre_payment_retry":
            retry_count = transaction_obj.payment_attempts.count()
            if retry_count >= RETRY_ATTEMPT_REVIEW_THRESHOLD:
                rule_score = 25
                score += rule_score
                triggered_rules.append(
                    cls._build_triggered_rule(
                        "retry_payment",
                        "重复发起支付",
                        rule_score,
                        {
                            "retry_count": retry_count,
                            "threshold": RETRY_ATTEMPT_REVIEW_THRESHOLD,
                        },
                    )
                )

        if customer_email:
            cutoff = timezone.now() - timezone.timedelta(hours=FAILED_ATTEMPT_LOOKBACK_HOURS)
            failed_attempt_count = Payment.objects.filter(
                order__customer_email__iexact=customer_email,
                status__in=[Payment.Status.FAILED, Payment.Status.CANCELLED],
                created_at__gte=cutoff,
            ).count()
            if failed_attempt_count >= FAILED_ATTEMPT_REVIEW_THRESHOLD:
                rule_score = 35
                score += rule_score
                triggered_rules.append(
                    cls._build_triggered_rule(
                        "repeated_failed_payments",
                        "同邮箱短时多次失败",
                        rule_score,
                        {
                            "customer_email": customer_email,
                            "failed_attempt_count": failed_attempt_count,
                            "threshold": FAILED_ATTEMPT_REVIEW_THRESHOLD,
                            "lookback_hours": FAILED_ATTEMPT_LOOKBACK_HOURS,
                        },
                    )
                )

        decision = RiskAssessment.Decision.REVIEW if triggered_rules else RiskAssessment.Decision.ALLOW
        return score, decision, triggered_rules

    @staticmethod
    def promote_transaction_risk_status(transaction_obj, decision):
        current_priority = RISK_STATUS_PRIORITY.get(transaction_obj.risk_status, 0)
        next_priority = RISK_STATUS_PRIORITY.get(decision, 0)
        if next_priority > current_priority:
            transaction_obj.risk_status = decision
            transaction_obj.save(update_fields=["risk_status", "updated_at"])
        return transaction_obj.risk_status

    @classmethod
    def observe(cls, transaction_obj, *, score=None, decision=None, triggered_rules=None, payload=None):
        if score is None and decision is None and triggered_rules is None:
            score, decision, triggered_rules = cls.evaluate(transaction_obj, payload=payload)
        else:
            score = 0 if score is None else score
            triggered_rules = triggered_rules or []
            decision = decision or (RiskAssessment.Decision.REVIEW if triggered_rules else RiskAssessment.Decision.ALLOW)
        assessment = RiskAssessment.objects.create(
            transaction=transaction_obj,
            score=score,
            decision=decision,
            triggered_rules=triggered_rules,
            payload=payload or {},
        )
        cls.promote_transaction_risk_status(transaction_obj, assessment.decision)
        return assessment
