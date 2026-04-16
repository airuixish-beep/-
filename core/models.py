from django.db import models


class SiteConfig(models.Model):
    site_name = models.CharField(max_length=100, default="XUANOR")
    site_title = models.CharField(max_length=200, default="XUANOR | Quiet symbols for modern life")
    site_description = models.TextField(blank=True)
    brand_tagline = models.CharField(max_length=200, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=50, blank=True)
    address = models.CharField(max_length=255, blank=True)
    logo = models.ImageField(upload_to="branding/", blank=True, null=True)
    favicon = models.ImageField(upload_to="branding/", blank=True, null=True)
    footer_text = models.CharField(max_length=255, blank=True)
    icp_number = models.CharField(max_length=100, blank=True)
    public_security_beian = models.CharField(max_length=100, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "站点配置"
        verbose_name_plural = "站点配置"

    def __str__(self):
        return self.site_name

    @classmethod
    def get_solo(cls):
        return cls.objects.first()
