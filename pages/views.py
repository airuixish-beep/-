from django.core.files.storage import default_storage
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from products.models import Product
from products.services import get_recommended_products

from .forms import FiveElementLeadCaptureForm, FiveElementQuizForm
from .models import FiveElementQuiz, FiveElementSubmission
from .services import build_result_summary, evaluate_five_element_result, get_profile_recommendations


def _build_score_breakdown_from_snapshot(quiz, score_snapshot):
    profiles = {profile.code: profile for profile in quiz.profiles.filter(is_active=True).order_by("sort_order", "id")}
    visible_codes = [code for code in score_snapshot.keys() if code in profiles]
    ordered_codes = sorted(visible_codes, key=lambda code: (-score_snapshot[code], profiles[code].sort_order, profiles[code].id))
    max_score = max((score_snapshot[code] for code in visible_codes), default=0)
    score_breakdown = []
    for code in ordered_codes:
        score = score_snapshot[code]
        score_breakdown.append(
            {
                "profile": profiles[code],
                "score": score,
                "strong_hits": None,
                "bar_width": max(12, int(score / max_score * 100)) if max_score and score > 0 else 0,
            }
        )
    return score_breakdown


FIVE_ELEMENT_PREVIEW = [
    {"name": "木", "theme_word": "生长", "summary": "不是变得更满，而是重新开始生长。"},
    {"name": "火", "theme_word": "回温", "summary": "不是更热烈，而是把生命热度慢慢找回来。"},
    {"name": "土", "theme_word": "承托", "summary": "不是更坚硬，而是重新被稳稳托住。"},
    {"name": "金", "theme_word": "清明", "summary": "不是更冷，而是从混乱里回到清明。"},
    {"name": "水", "theme_word": "深度", "summary": "不是逃离外界，而是退回内在深处。"},
]


def home(request):
    recommended_products = get_recommended_products(limit=4)
    quiz = FiveElementQuiz.objects.filter(is_active=True).order_by("sort_order", "id").first()
    return render(
        request,
        "pages/home.html",
        {
            "recommended_products": recommended_products,
            "five_element_quiz": quiz,
            "five_element_preview": FIVE_ELEMENT_PREVIEW,
        },
    )


def five_element_quiz_landing(request, slug):
    quiz = _get_active_quiz(slug)
    profiles = list(quiz.profiles.filter(is_active=True).order_by("sort_order", "id"))
    question_count = quiz.questions.filter(is_active=True).count()
    return render(
        request,
        "pages/five_element_quiz_landing.html",
        {
            "quiz": quiz,
            "profiles": profiles,
            "question_count": question_count,
        },
    )


def five_element_quiz_take(request, slug):
    quiz = _get_active_quiz(slug)
    if request.method == "POST":
        form = FiveElementQuizForm(request.POST, quiz=quiz)
        if form.is_valid():
            evaluation = evaluate_five_element_result(quiz=quiz, option_ids=form.selected_option_ids())
            submission = FiveElementSubmission.objects.create(
                quiz=quiz,
                primary_profile=evaluation["primary_profile"],
                secondary_profile=evaluation["secondary_profile"] if evaluation["is_close_match"] else None,
                respondent_name=form.cleaned_data.get("respondent_name", ""),
                respondent_email=form.cleaned_data.get("respondent_email", ""),
                answers_json=form.build_submission_payload(),
                score_snapshot=evaluation["score_snapshot"],
                utm_source=(request.GET.get("utm_source") or "").strip(),
                utm_medium=(request.GET.get("utm_medium") or "").strip(),
                utm_campaign=(request.GET.get("utm_campaign") or "").strip(),
            )
            return redirect("pages:five_element_quiz_result", slug=quiz.slug, token=submission.token)
    else:
        form = FiveElementQuizForm(quiz=quiz)

    question_forms = [(question, form[f"question_{question.id}"]) for question in form.questions]
    return render(
        request,
        "pages/five_element_quiz_take.html",
        {
            "quiz": quiz,
            "form": form,
            "question_forms": question_forms,
            "question_count": len(question_forms),
        },
    )


def five_element_quiz_result(request, slug, token):
    quiz = _get_active_quiz(slug)
    submission = get_object_or_404(
        FiveElementSubmission.objects.select_related("quiz", "primary_profile", "secondary_profile"),
        quiz=quiz,
        token=token,
    )
    if submission.primary_profile is None:
        raise Http404("结果尚未生成。")

    if request.method == "POST":
        lead_form = FiveElementLeadCaptureForm(request.POST, instance=submission, require_email=True)
        if lead_form.is_valid():
            lead_form.save()
            return redirect("pages:five_element_quiz_result", slug=quiz.slug, token=submission.token)
    else:
        lead_form = FiveElementLeadCaptureForm(instance=submission)

    recommendations = get_profile_recommendations(submission.primary_profile)
    score_breakdown = _build_score_breakdown_from_snapshot(quiz, submission.score_snapshot)
    primary_score = score_breakdown[0]["score"] if score_breakdown else 0
    secondary_score = score_breakdown[1]["score"] if len(score_breakdown) > 1 else 0
    score_gap = primary_score - secondary_score
    total_score = sum(item["score"] for item in score_breakdown)
    result_summary = build_result_summary(submission.primary_profile, submission.secondary_profile)
    return render(
        request,
        "pages/five_element_quiz_result.html",
        {
            "quiz": quiz,
            "submission": submission,
            "primary_profile": submission.primary_profile,
            "secondary_profile": submission.secondary_profile,
            "recommendations": recommendations,
            "score_breakdown": score_breakdown,
            "primary_score": primary_score,
            "secondary_score": secondary_score,
            "score_gap": score_gap,
            "total_score": total_score,
            "lead_form": lead_form,
            "lead_capture_complete": bool(submission.respondent_email),
            "result_summary": result_summary,
        },
    )


def about(request):
    return render(request, "pages/about.html")


def contact(request):
    return render(request, "pages/contact.html")


def refund_policy(request):
    return render(request, "pages/refund_policy.html")


def shipping_policy(request):
    return render(request, "pages/shipping_policy.html")


def privacy_policy(request):
    return render(request, "pages/privacy_policy.html")


def terms_of_service(request):
    return render(request, "pages/terms_of_service.html")


def chat(request):
    consultation_product = Product.objects.filter(is_active=True, hero_image__isnull=False).order_by("sort_order", "-created_at").first()
    return render(
        request,
        "pages/chat.html",
        {
            "hide_support_chat_widget": True,
            "consultation_product": consultation_product,
            "prefill_name": (request.GET.get("name") or "").strip(),
            "prefill_email": (request.GET.get("email") or "").strip(),
            "prefill_order_no": (request.GET.get("order_no") or "").strip(),
        },
    )


def upload_test(request):
    upload_result = None

    if request.method == "POST" and request.FILES.get("test_file"):
        uploaded_file = request.FILES["test_file"]
        saved_path = default_storage.save(f"uploads/{uploaded_file.name}", uploaded_file)
        upload_result = {
            "name": uploaded_file.name,
            "path": saved_path,
            "url": default_storage.url(saved_path),
            "size": uploaded_file.size,
            "content_type": uploaded_file.content_type,
        }

    return render(request, "pages/upload_test.html", {"upload_result": upload_result})


def _get_active_quiz(slug):
    return get_object_or_404(
        FiveElementQuiz.objects.prefetch_related(
            "profiles",
            "questions__options__scores",
        ),
        slug=slug,
        is_active=True,
    )
