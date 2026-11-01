from django.db import models


class Document(models.Model):
    """یک فایل PDF واردشده. متن کامل فقط در پایگاه داده و برای مدیر است."""

    file_name = models.CharField("نام فایل", max_length=255, unique=True)
    source_path = models.TextField("مسیر مبدأ", blank=True)
    file_hash = models.CharField("هش محتوا", max_length=64, db_index=True)
    file_size = models.PositiveBigIntegerField("حجم فایل", default=0)
    page_count = models.PositiveIntegerField("تعداد صفحه", default=0)
    text_page_count = models.PositiveIntegerField("صفحات دارای متن", default=0)
    chunk_count = models.PositiveIntegerField("تعداد بخش", default=0)
    is_scanned = models.BooleanField("اسکن‌شده / بدون متن", default=False)
    scanned_pages = models.JSONField("صفحات بدون متن", default=list, blank=True)
    imported_at = models.DateTimeField("زمان اولین ورود", auto_now_add=True)
    updated_at = models.DateTimeField("زمان آخرین به‌روزرسانی", auto_now=True)

    class Meta:
        verbose_name = "جزوه"
        verbose_name_plural = "جزوه‌ها"
        ordering = ["file_name"]

    def __str__(self):
        return self.file_name


class Page(models.Model):
    """متن استخراج‌شدهٔ یک صفحه. در صفحات مدیریت فقط شماره و تعداد نویسه نمایش داده می‌شود."""

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="pages")
    number = models.PositiveIntegerField("شمارهٔ صفحه")
    text = models.TextField("متن صفحه", blank=True)
    char_count = models.PositiveIntegerField("تعداد نویسه", default=0)

    class Meta:
        verbose_name = "صفحه"
        verbose_name_plural = "صفحات"
        ordering = ["document", "number"]
        constraints = [
            models.UniqueConstraint(fields=["document", "number"], name="uniq_document_page"),
        ]

    def __str__(self):
        return f"{self.document.file_name} — صفحهٔ {self.number}"


class Chunk(models.Model):
    """بخش کوچک‌تر صفحه برای بازیابی متنی. متن آن هرگز به کاربر عادی نمایش داده نمی‌شود."""

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="chunks")
    order = models.PositiveIntegerField("ترتیب در سند")
    text = models.TextField("متن بخش")
    search_text = models.TextField("متن نرمال‌شده برای جستجو", blank=True)
    char_count = models.PositiveIntegerField("تعداد نویسه", default=0)

    class Meta:
        verbose_name = "بخش"
        verbose_name_plural = "بخش‌ها"
        ordering = ["document", "order"]
        constraints = [
            models.UniqueConstraint(fields=["document", "order"], name="uniq_document_chunk_order"),
        ]

    def __str__(self):
        return f"{self.document.file_name} — صفحهٔ {self.page.number} — بخش {self.order}"
