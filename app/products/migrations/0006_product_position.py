from django.db import migrations, models


def number_existing_products(apps, schema_editor):
    # Keep today's order (oldest first) as the starting order.
    Product = apps.get_model('products', 'Product')
    for index, product in enumerate(Product.objects.order_by('id')):
        Product.objects.filter(pk=product.pk).update(position=index)


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0005_alter_product_price_alter_product_sale_price'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='product',
            options={'ordering': ['position', 'id']},
        ),
        migrations.AddField(
            model_name='product',
            name='position',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(number_existing_products, migrations.RunPython.noop),
    ]
