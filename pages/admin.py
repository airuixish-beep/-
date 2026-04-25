from django.contrib import admin

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


@admin.register(FiveElementSubmission)
class FiveElementSubmissionAdmin(admin.ModelAdmin):
    list_display = ("quiz", "primary_profile", "secondary_profile", "respondent_email", "created_at")
    list_filter = ("quiz", "primary_profile", "secondary_profile", "created_at")
    search_fields = ("respondent_name", "respondent_email", "token")
    readonly_fields = (
        "token",
        "quiz",
        "primary_profile",
        "secondary_profile",
        "respondent_name",
        "respondent_email",
        "answers_json",
        "score_snapshot",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
