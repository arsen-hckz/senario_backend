from django.db import migrations, models
import django.db.models.deletion


def copy_single_images(apps, schema_editor):
    """Each product's existing photo becomes its first gallery photo (same file)."""
    Product = apps.get_model('products', 'Product')
    ProductImage = apps.get_model('products', 'ProductImage')
    ProductImage.objects.bulk_create([
        ProductImage(product=p, image=p.image.name, order=0)
        for p in Product.objects.exclude(image='').exclude(image__isnull=True)
    ])


def restore_single_images(apps, schema_editor):
    Product = apps.get_model('products', 'Product')
    ProductImage = apps.get_model('products', 'ProductImage')
    for p in Product.objects.all():
        first = ProductImage.objects.filter(product=p).order_by('order', 'id').first()
        if first:
            p.image = first.image.name
            p.save(update_fields=['image'])


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0003_alter_product_image'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(upload_to='products/')),
                ('order', models.PositiveIntegerField(default=0)),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='images', to='products.product')),
            ],
            options={
                'ordering': ['order', 'id'],
            },
        ),
        migrations.RunPython(copy_single_images, restore_single_images),
        migrations.RemoveField(
            model_name='product',
            name='image',
        ),
    ]
