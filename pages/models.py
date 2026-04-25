import uuid

from django.db import models

from products.models import Product


class FiveElementQuiz(models.Model):
    name = models.CharField("测试名称", max_length=120)
    slug = models.SlugField("访问标识", unique=True)
    title = models.CharField("前台标题", max_length=160)
    subtitle = models.CharField("前台副标题", max_length=255, blank=True)
    intro_title = models.CharField("介绍标题", max_length=160, blank=True)
    intro_body = models.TextField("介绍文案", blank=True)
    estimated_minutes = models.PositiveSmallIntegerField("预计时长（分钟）", default=3)
    sort_order = models.PositiveIntegerField("排序值", default=0)
    is_active = models.BooleanField("是否启用", default=False)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "五行测试"
        verbose_name_plural = "五行测试"

    def __str__(self):
        return self.name


class FiveElementProfile(models.Model):
    class ElementCode(models.TextChoices):
        WOOD = "wood", "木"
        FIRE = "fire", "火"
        EARTH = "earth", "土"
        METAL = "metal", "金"
        WATER = "water", "水"

    quiz = models.ForeignKey(FiveElementQuiz, verbose_name="所属测试", on_delete=models.CASCADE, related_name="profiles")
    code = models.CharField("元素代码", max_length=10, choices=ElementCode.choices)
    name = models.CharField("结果名称", max_length=40)
    theme_word = models.CharField("主题词", max_length=40)
    emotion_title = models.CharField("情绪命名标题", max_length=160)
    emotion_body = models.TextField("情绪命名文案")
    result_title = models.CharField("结果标题", max_length=160)
    short_description = models.CharField("短描述", max_length=255, blank=True)
    long_description = models.TextField("长描述", blank=True)
    primary_symbol_title = models.CharField("主符号标题", max_length=120)
    primary_symbol_description = models.TextField("主符号文案", blank=True)
    ritual_object_title = models.CharField("仪式物标题", max_length=120)
    ritual_object_description = models.TextField("仪式物文案", blank=True)
    ambient_object_title = models.CharField("氛围物标题", max_length=120)
    ambient_object_description = models.TextField("氛围物文案", blank=True)
    sort_order = models.PositiveIntegerField("排序值", default=0)
    is_active = models.BooleanField("是否启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "五行结果"
        verbose_name_plural = "五行结果"
        constraints = [
            models.UniqueConstraint(fields=["quiz", "code"], name="unique_five_element_profile_code_per_quiz"),
        ]

    def __str__(self):
        return f"{self.quiz.name} - {self.name}"


class FiveElementQuestion(models.Model):
    quiz = models.ForeignKey(FiveElementQuiz, verbose_name="所属测试", on_delete=models.CASCADE, related_name="questions")
    prompt = models.CharField("题目", max_length=255)
    help_text = models.CharField("辅助文案", max_length=255, blank=True)
    sort_order = models.PositiveIntegerField("排序值", default=0)
    is_active = models.BooleanField("是否启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "测试题目"
        verbose_name_plural = "测试题目"

    def __str__(self):
        return self.prompt


class FiveElementOption(models.Model):
    question = models.ForeignKey(FiveElementQuestion, verbose_name="所属题目", on_delete=models.CASCADE, related_name="options")
    label = models.CharField("选项文案", max_length=255)
    sort_order = models.PositiveIntegerField("排序值", default=0)
    is_active = models.BooleanField("是否启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "测试选项"
        verbose_name_plural = "测试选项"

    def __str__(self):
        return self.label


class FiveElementOptionScore(models.Model):
    option = models.ForeignKey(FiveElementOption, verbose_name="所属选项", on_delete=models.CASCADE, related_name="scores")
    profile = models.ForeignKey(FiveElementProfile, verbose_name="结果元素", on_delete=models.CASCADE, related_name="option_scores")
    score = models.PositiveSmallIntegerField("得分", default=1)

    class Meta:
        ordering = ["-score", "id"]
        verbose_name = "选项得分映射"
        verbose_name_plural = "选项得分映射"
        constraints = [
            models.UniqueConstraint(fields=["option", "profile"], name="unique_five_element_option_profile_score"),
        ]

    def __str__(self):
        return f"{self.option.label} -> {self.profile.name} ({self.score})"


class FiveElementProfileProduct(models.Model):
    class ProductRole(models.TextChoices):
        PRIMARY_SYMBOL = "primary_symbol", "主符号"
        RITUAL_OBJECT = "ritual_object", "仪式物"
        AMBIENT_OBJECT = "ambient_object", "氛围/承接物"
        BACKUP = "backup", "备用推荐"

    profile = models.ForeignKey(FiveElementProfile, verbose_name="所属结果", on_delete=models.CASCADE, related_name="product_mappings")
    product = models.ForeignKey(Product, verbose_name="关联商品", on_delete=models.CASCADE, related_name="five_element_mappings")
    role = models.CharField("推荐角色", max_length=20, choices=ProductRole.choices)
    blurb = models.CharField("推荐说明", max_length=255, blank=True)
    sort_order = models.PositiveIntegerField("排序值", default=0)
    is_active = models.BooleanField("是否启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "结果推荐商品"
        verbose_name_plural = "结果推荐商品"

    def __str__(self):
        return f"{self.profile.name} - {self.product.name}"


class FiveElementSubmission(models.Model):
    token = models.UUIDField("结果令牌", default=uuid.uuid4, editable=False, unique=True)
    quiz = models.ForeignKey(FiveElementQuiz, verbose_name="所属测试", on_delete=models.CASCADE, related_name="submissions")
    primary_profile = models.ForeignKey(
        FiveElementProfile,
        verbose_name="主结果",
        on_delete=models.SET_NULL,
        related_name="primary_submissions",
        blank=True,
        null=True,
    )
    secondary_profile = models.ForeignKey(
        FiveElementProfile,
        verbose_name="次级结果",
        on_delete=models.SET_NULL,
        related_name="secondary_submissions",
        blank=True,
        null=True,
    )
    respondent_name = models.CharField("姓名", max_length=120, blank=True)
    respondent_email = models.EmailField("邮箱", blank=True)
    answers_json = models.JSONField("答案快照", default=list, blank=True)
    score_snapshot = models.JSONField("得分快照", default=dict, blank=True)
    utm_source = models.CharField("UTM Source", max_length=120, blank=True)
    utm_medium = models.CharField("UTM Medium", max_length=120, blank=True)
    utm_campaign = models.CharField("UTM Campaign", max_length=120, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "测试提交记录"
        verbose_name_plural = "测试提交记录"

    def __str__(self):
        return f"{self.quiz.name} - {self.primary_profile or '未生成结果'} - {self.created_at:%Y-%m-%d %H:%M}"
