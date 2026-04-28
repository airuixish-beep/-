import csv
import json

from django.contrib import admin
from django.http import HttpResponse

from .models import (
    FiveElementOption,
    FiveElementOptionScore,
    FiveElementProfile,
    FiveElementProfileProduct,
    FiveElementQuestion,
    FiveElementQuiz,
    FiveElementSubmission,
)


class FiveElementOptionScoreInline(admin.TabularInline):
    model = FiveElementOptionScore
    extra = 1
    fields = ("profile", "score")


class FiveElementOptionInline(admin.TabularInline):
    model = FiveElementOption
    extra = 1
    fields = ("label", "sort_order", "is_active")
    ordering = ("sort_order", "id")
    show_change_link = True


class FiveElementQuestionInline(admin.TabularInline):
    model = FiveElementQuestion
    extra = 1
    fields = ("prompt", "sort_order", "is_active")
    ordering = ("sort_order", "id")
    show_change_link = True


class FiveElementProfileProductInline(admin.TabularInline):
    model = FiveElementProfileProduct
    extra = 1
    fields = ("product", "role", "blurb", "sort_order", "is_active")
    ordering = ("sort_order", "id")
    autocomplete_fields = ("product",)


@admin.register(FiveElementQuiz)
class FiveElementQuizAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "estimated_minutes", "is_active", "sort_order", "updated_at")
    list_filter = ("is_active",)
    list_editable = ("is_active", "sort_order")
    search_fields = ("name", "slug", "title", "subtitle")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [FiveElementQuestionInline]
    fieldsets = (
        ("基础信息", {"fields": ("name", "slug", "title", "subtitle")}),
        ("介绍内容", {"fields": ("intro_title", "intro_body")}),
        ("显示设置", {"fields": ("estimated_minutes", "sort_order", "is_active")}),
    )


@admin.register(FiveElementProfile)
class FiveElementProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "quiz", "code", "theme_word", "is_active", "sort_order", "updated_at")
    list_filter = ("quiz", "code", "is_active")
    list_editable = ("is_active", "sort_order")
    search_fields = ("name", "theme_word", "emotion_title", "result_title")
    inlines = [FiveElementProfileProductInline]
    fieldsets = (
        ("基础信息", {"fields": ("quiz", "code", "name", "theme_word")}),
        ("情绪价值", {"fields": ("emotion_title", "emotion_body")}),
        ("结果文案", {"fields": ("result_title", "short_description", "long_description")}),
        (
            "仪式结构",
            {
                "fields": (
                    "primary_symbol_title",
                    "primary_symbol_description",
                    "ritual_object_title",
                    "ritual_object_description",
                    "ambient_object_title",
                    "ambient_object_description",
                )
            },
        ),
        ("显示设置", {"fields": ("sort_order", "is_active")}),
    )


@admin.register(FiveElementQuestion)
class FiveElementQuestionAdmin(admin.ModelAdmin):
    list_display = ("prompt", "quiz", "sort_order", "is_active", "updated_at")
    list_filter = ("quiz", "is_active")
    list_editable = ("sort_order", "is_active")
    search_fields = ("prompt", "help_text")
    inlines = [FiveElementOptionInline]
    fieldsets = (("基础信息", {"fields": ("quiz", "prompt", "help_text", "sort_order", "is_active")}),)


@admin.register(FiveElementOption)
class FiveElementOptionAdmin(admin.ModelAdmin):
    list_display = ("label", "question", "sort_order", "is_active", "updated_at")
    list_filter = ("question__quiz", "is_active")
    list_editable = ("sort_order", "is_active")
    search_fields = ("label", "question__prompt")
    inlines = [FiveElementOptionScoreInline]


class HasEmailListFilter(admin.SimpleListFilter):
    title = "是否留邮箱"
    parameter_name = "has_email"

    def lookups(self, request, model_admin):
        return (("yes", "有邮箱"), ("no", "无邮箱"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.exclude(respondent_email="")
        if self.value() == "no":
            return queryset.filter(respondent_email="")
        return queryset


class HasSourceListFilter(admin.SimpleListFilter):
    title = "是否有来源"
    parameter_name = "has_source"

    def lookups(self, request, model_admin):
        return (("yes", "有来源"), ("no", "直接访问"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.exclude(utm_source="", utm_medium="", utm_campaign="")
        if self.value() == "no":
            return queryset.filter(utm_source="", utm_medium="", utm_campaign="")
        return queryset


class HasSecondaryProfileListFilter(admin.SimpleListFilter):
    title = "次级结果"
    parameter_name = "has_secondary_profile"

    def lookups(self, request, model_admin):
        return (("yes", "有次级结果"), ("no", "无次级结果"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.exclude(secondary_profile__isnull=True)
        if self.value() == "no":
            return queryset.filter(secondary_profile__isnull=True)
        return queryset


@admin.register(FiveElementSubmission)
class FiveElementSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "quiz",
        "primary_profile",
        "secondary_profile",
        "lead_status",
        "respondent_name",
        "respondent_email",
        "lead_source_summary",
    )
    list_filter = (
        "quiz",
        "primary_profile",
        "secondary_profile",
        HasSecondaryProfileListFilter,
        HasEmailListFilter,
        HasSourceListFilter,
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "created_at",
    )
    list_select_related = ("quiz", "primary_profile", "secondary_profile")
    search_fields = ("respondent_name", "respondent_email", "token", "utm_source", "utm_medium", "utm_campaign")
    actions = ["export_selected_submissions"]
    readonly_fields = (
        "token",
        "quiz",
        "primary_profile",
        "secondary_profile",
        "respondent_name",
        "respondent_email",
        "answers_json_pretty",
        "score_snapshot_pretty",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        ("结果信息", {"fields": ("token", "quiz", "primary_profile", "secondary_profile", "created_at")}),
        ("留资信息", {"fields": ("respondent_name", "respondent_email")}),
        ("投放来源", {"fields": ("utm_source", "utm_medium", "utm_campaign")}),
        ("答案快照", {"fields": ("answers_json_pretty", "score_snapshot_pretty")}),
        ("系统信息", {"fields": ("updated_at",)}),
    )

    @admin.display(description="留资状态")
    def lead_status(self, obj):
        return "已留资" if obj.respondent_email else "未留资"

    @admin.display(description="来源")
    def lead_source_summary(self, obj):
        parts = [value for value in (obj.utm_source, obj.utm_medium, obj.utm_campaign) if value]
        return " / ".join(parts) if parts else "直接访问"

    @admin.display(description="答案快照")
    def answers_json_pretty(self, obj):
        return json.dumps(obj.answers_json, ensure_ascii=False, indent=2)

    @admin.display(description="得分快照")
    def score_snapshot_pretty(self, obj):
        return json.dumps(obj.score_snapshot, ensure_ascii=False, indent=2)

    @admin.action(description="导出所选提交为 CSV")
    def export_selected_submissions(self, request, queryset):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="five-element-submissions.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "created_at",
                "quiz",
                "primary_profile",
                "secondary_profile",
                "respondent_name",
                "respondent_email",
                "utm_source",
                "utm_medium",
                "utm_campaign",
                "token",
            ]
        )
        for submission in queryset.select_related("quiz", "primary_profile", "secondary_profile"):
            writer.writerow(
                [
                    submission.created_at.isoformat(),
                    submission.quiz.name,
                    submission.primary_profile.name if submission.primary_profile else "",
                    submission.secondary_profile.name if submission.secondary_profile else "",
                    submission.respondent_name,
                    submission.respondent_email,
                    submission.utm_source,
                    submission.utm_medium,
                    submission.utm_campaign,
                    submission.token,
                ]
            )
        return response

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
