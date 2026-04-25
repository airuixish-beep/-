from collections import defaultdict

from .models import FiveElementOption, FiveElementProfileProduct


def evaluate_five_element_result(*, quiz, option_ids):
    profiles = list(quiz.profiles.filter(is_active=True).order_by("sort_order", "id"))
    profile_by_id = {profile.id: profile for profile in profiles}
    scores = {profile.id: 0 for profile in profiles}
    strong_hits = {profile.id: 0 for profile in profiles}

    selected_options = list(
        FiveElementOption.objects.filter(
            question__quiz=quiz,
            question__is_active=True,
            is_active=True,
            id__in=option_ids,
        ).prefetch_related("scores__profile")
    )

    for option in selected_options:
        for option_score in option.scores.all():
            if option_score.profile_id not in scores:
                continue
            scores[option_score.profile_id] += option_score.score
            if option_score.score >= 2:
                strong_hits[option_score.profile_id] += 1

    ranked_profiles = sorted(
        profiles,
        key=lambda profile: (
            -scores[profile.id],
            -strong_hits[profile.id],
            profile.sort_order,
            profile.id,
        ),
    )

    primary_profile = ranked_profiles[0] if ranked_profiles else None
    secondary_profile = ranked_profiles[1] if len(ranked_profiles) > 1 else None
    is_close_match = False
    if primary_profile and secondary_profile:
        is_close_match = scores[primary_profile.id] - scores[secondary_profile.id] <= 1

    score_breakdown = [
        {
            "profile": profile,
            "score": scores[profile.id],
            "strong_hits": strong_hits[profile.id],
        }
        for profile in ranked_profiles
    ]

    return {
        "primary_profile": primary_profile,
        "secondary_profile": secondary_profile,
        "is_close_match": is_close_match,
        "score_breakdown": score_breakdown,
        "score_snapshot": {profile.code: scores[profile.id] for profile in ranked_profiles},
    }


def get_profile_recommendations(profile):
    role_order = {
        FiveElementProfileProduct.ProductRole.PRIMARY_SYMBOL: 0,
        FiveElementProfileProduct.ProductRole.RITUAL_OBJECT: 1,
        FiveElementProfileProduct.ProductRole.AMBIENT_OBJECT: 2,
        FiveElementProfileProduct.ProductRole.BACKUP: 3,
    }
    mappings = list(
        profile.product_mappings.filter(is_active=True, product__is_active=True)
        .select_related("product", "product__category")
        .order_by("role", "sort_order", "id")
    )

    grouped = defaultdict(list)
    for mapping in mappings:
        grouped[mapping.role].append(mapping)

    recommendations = []
    used_product_ids = set()
    for role in (
        FiveElementProfileProduct.ProductRole.PRIMARY_SYMBOL,
        FiveElementProfileProduct.ProductRole.RITUAL_OBJECT,
        FiveElementProfileProduct.ProductRole.AMBIENT_OBJECT,
    ):
        selected = _pick_mapping(grouped.get(role, []), used_product_ids)
        if selected is None:
            selected = _pick_mapping(grouped.get(FiveElementProfileProduct.ProductRole.BACKUP, []), used_product_ids)
        if selected is None:
            continue
        used_product_ids.add(selected.product_id)
        recommendations.append(
            {
                "role": role,
                "role_label": dict(FiveElementProfileProduct.ProductRole.choices)[role],
                "mapping": selected,
                "product": selected.product,
            }
        )

    recommendations.sort(key=lambda item: role_order[item["role"]])
    return recommendations


def _pick_mapping(candidates, used_product_ids):
    def ranking_key(mapping):
        product = mapping.product
        return (
            0 if product.can_purchase else 1,
            0 if product.in_stock else 1,
            0 if product.is_featured else 1,
            mapping.sort_order,
            product.sort_order,
            -product.id,
        )

    for mapping in sorted(candidates, key=ranking_key):
        if mapping.product_id in used_product_ids:
            continue
        return mapping
    return None
