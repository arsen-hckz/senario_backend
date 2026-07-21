from django.contrib import admin
from .models import Category, Product, ProductVariant


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    prepopulated_fields = {'slug': ('name',)}
    list_display = ('name', 'slug')


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    prepopulated_fields = {'slug': ('name',)}
    list_display = ('name', 'category', 'price', 'sale_price', 'stock', 'is_active', 'created_at')
    list_filter = ('is_active', 'category')
    search_fields = ('name',)
    inlines = (ProductVariantInline,)
