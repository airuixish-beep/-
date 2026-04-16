from django.db import models


class SiteConfig(models.Model):
    site_name = models.CharField("站点名称", max_length=100, default="XUANOR")
    site_title = models.CharField("站点标题", max_length=200, default="XUANOR | Quiet symbols for modern life")
    site_description = models.TextField("站点描述", blank=True)
    brand_tagline = models.CharField("品牌标语", max_length=200, blank=True)
    contact_email = models.EmailField("联系邮箱", blank=True)
    contact_phone = models.CharField("联系电话", max_length=50, blank=True)
    address = models.CharField("联系地址", max_length=255, blank=True)
    logo = models.ImageField("站点 Logo", upload_to="branding/", blank=True, null=True)
    favicon = models.ImageField("站点图标", upload_to="branding/", blank=True, null=True)
    footer_text = models.CharField("页脚文案", max_length=255, blank=True)
    icp_number = models.CharField("ICP备案号", max_length=100, blank=True)
    public_security_beian = models.CharField("公安备案号", max_length=100, blank=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "站点配置"
        verbose_name_plural = "站点配置"

    def __str__(self):
        return self.site_name

    @classmethod
    def get_solo(cls):
        return cls.objects.first()
