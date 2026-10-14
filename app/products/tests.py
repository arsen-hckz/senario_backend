import io
import os
import tempfile

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django_redis import get_redis_connection
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Category, Product, ProductImage

User = get_user_model()


class ProductListCacheTests(APITestCase):
    def setUp(self):
        cache.clear()
        shirts = Category.objects.create(name='Shirts', slug='shirts')
        Product.objects.create(category=shirts, name='Tee', slug='tee', price='20.00')

    def tearDown(self):
        cache.clear()

    def product_cache_keys(self):
        return get_redis_connection('default').keys('*products:*')

    def test_junk_query_params_share_one_cache_entry(self):
        """Arbitrary params used to each create their own cache entry,
        letting anyone fill Redis with one request per made-up URL."""
        for i in range(5):
            res = self.client.get(f'/api/products/?junk={i}')
            self.assertEqual(len(res.data), 1)
        self.assertEqual(len(self.product_cache_keys()), 1)

    def test_searches_and_unknown_categories_are_not_cached(self):
        for i in range(3):
            self.client.get(f'/api/products/?search=tee{i}')
            self.client.get(f'/api/products/?category=nope{i}')
        self.assertEqual(self.product_cache_keys(), [])

    def test_any_product_save_clears_the_list_cache(self):
        # e.g. an edit in the Django admin, which bypasses the API views
        self.client.get('/api/products/')
        self.assertEqual(len(self.product_cache_keys()), 1)
        with self.captureOnCommitCallbacks(execute=True):
            Product.objects.update_or_create(slug='tee', defaults={'price': '25.00'})
        self.assertEqual(self.product_cache_keys(), [])
        self.assertEqual(self.client.get('/api/products/').data[0]['price'], '25.00')

    def test_category_filter_is_cached_separately(self):
        self.assertEqual(len(self.client.get('/api/products/?category=shirts').data), 1)
        self.assertEqual(len(self.client.get('/api/products/').data), 1)
        self.assertEqual(len(self.product_cache_keys()), 2)


def make_jpeg(name='photo.jpg', size=(3000, 2000), color=(200, 80, 40)):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, format='JPEG', quality=100)
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/jpeg')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ProductGalleryTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user(email='staff@example.com', password='x-pass-123', is_staff=True)
        self.client.force_authenticate(self.staff)

    def create(self, files, **extra):
        data = {'name': 'Hoodie', 'price': '50.00', 'stock': 3, 'is_active': 'true', 'uploaded_images': files, **extra}
        return self.client.post('/api/products/admin/', data, format='multipart')

    def patch(self, pk, **data):
        return self.client.patch(f'/api/products/admin/{pk}/', data, format='multipart')

    def test_create_with_several_photos_keeps_order_and_cover(self):
        res = self.create([make_jpeg('a.jpg'), make_jpeg('b.jpg'), make_jpeg('c.jpg')])
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        names = [img['image'].rsplit('/', 1)[1] for img in res.data['images']]
        self.assertEqual([n[0] for n in names], ['a', 'b', 'c'])
        self.assertEqual(res.data['image'], res.data['images'][0]['image'])
        self.assertTrue(res.data['image'].startswith('http://testserver/media/products/'))

    def test_uploads_are_downsized(self):
        res = self.create([make_jpeg(size=(4000, 3000))])
        photo = ProductImage.objects.get(pk=res.data['images'][0]['id'])
        with Image.open(photo.image.path) as img:
            self.assertEqual(max(img.size), 2000)

    def test_patch_removes_reorders_and_appends(self):
        res = self.create([make_jpeg('a.jpg'), make_jpeg('b.jpg'), make_jpeg('c.jpg')])
        pk = res.data['id']
        a, b, c = [img['id'] for img in res.data['images']]
        removed_path = ProductImage.objects.get(pk=b).image.path

        with self.captureOnCommitCallbacks(execute=True):  # files are deleted on commit
            res = self.patch(pk, remove_image_ids=[b], image_order=[c, a], uploaded_images=[make_jpeg('d.jpg')])
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        ids = [img['id'] for img in res.data['images']]
        self.assertEqual(ids[:2], [c, a])
        self.assertEqual(len(ids), 3)
        self.assertEqual(res.data['images'][2]['image'].rsplit('/', 1)[1][0], 'd')
        self.assertFalse(os.path.exists(removed_path))

    def test_new_upload_can_become_the_cover(self):
        res = self.create([make_jpeg('a.jpg'), make_jpeg('b.jpg')])
        a, b = [img['id'] for img in res.data['images']]
        res = self.patch(res.data['id'], uploaded_images=[make_jpeg('n.jpg')], image_order=['new-0', b, a])
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(res.data['image'].rsplit('/', 1)[1][0], 'n')
        self.assertEqual([img['id'] for img in res.data['images']][1:], [b, a])

    def test_patch_without_gallery_fields_leaves_photos_alone(self):
        res = self.create([make_jpeg('a.jpg'), make_jpeg('b.jpg')])
        res = self.patch(res.data['id'], price='45.00')
        self.assertEqual(len(res.data['images']), 2)

    def test_cannot_remove_or_reorder_another_products_photos(self):
        other = self.create([make_jpeg('x.jpg')]).data
        mine = self.create([make_jpeg('a.jpg')]).data
        other_photo = other['images'][0]['id']

        self.patch(mine['id'], remove_image_ids=[other_photo], image_order=[other_photo])
        self.assertTrue(ProductImage.objects.filter(pk=other_photo, product_id=other['id']).exists())

    def test_deleting_product_deletes_its_photo_files(self):
        res = self.create([make_jpeg('a.jpg'), make_jpeg('b.jpg')])
        paths = [p.image.path for p in ProductImage.objects.all()]
        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(f'/api/products/admin/{res.data["id"]}/')
        self.assertEqual([os.path.exists(p) for p in paths], [False, False])

    def test_negative_prices_are_rejected(self):
        self.assertEqual(self.create([], price='-5').status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.create([], sale_price='-1').status_code, status.HTTP_400_BAD_REQUEST)

    def test_photo_limit(self):
        pk = self.create([make_jpeg(size=(50, 50)) for _ in range(10)]).data['id']
        res = self.patch(pk, uploaded_images=[make_jpeg(size=(50, 50)) for _ in range(3)])
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ProductImage.objects.filter(product_id=pk).count(), 10)

    def test_non_staff_cannot_edit_gallery(self):
        pk = self.create([make_jpeg()]).data['id']
        customer = User.objects.create_user(email='c@example.com', password='x-pass-123')
        self.client.force_authenticate(customer)
        res = self.patch(pk, remove_image_ids=[1])
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_public_list_and_detail_show_gallery(self):
        res = self.create([make_jpeg('a.jpg'), make_jpeg('b.jpg')])
        self.client.force_authenticate(None)
        listing = self.client.get('/api/products/').data
        self.assertEqual(len(listing[0]['images']), 2)
        detail = self.client.get(f"/api/products/{res.data['slug']}/").data
        self.assertEqual(detail['image'], detail['images'][0]['image'])

    def test_product_without_photos_has_null_image(self):
        res = self.create([])
        self.assertIsNone(res.data['image'])
        self.assertEqual(res.data['images'], [])


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class OptimizeImagesCommandTests(APITestCase):
    def test_shrinks_large_stored_photos_and_dry_run_changes_nothing(self):
        product = Product.objects.create(name='Tee', slug='tee', price='20.00')
        photo = ProductImage(product=product, order=0)
        # Store a large original directly, the way pre-optimization uploads were stored.
        photo.image.save('big.jpg', ContentFile(make_jpeg(size=(4000, 3000)).read()), save=False)
        ProductImage.objects.bulk_create([photo])
        photo = ProductImage.objects.get(product=product)
        before = photo.image.size

        call_command('optimize_images', '--dry-run', stdout=io.StringIO())
        self.assertEqual(ProductImage.objects.get(pk=photo.pk).image.size, before)

        out = io.StringIO()
        call_command('optimize_images', stdout=out)
        photo = ProductImage.objects.get(pk=photo.pk)
        self.assertLess(photo.image.size, before)
        self.assertEqual(photo.image.name, 'products/big.jpg')
        with Image.open(photo.image.path) as img:
            self.assertEqual(max(img.size), 2000)


class ProductSizesTests(APITestCase):
    def setUp(self):
        cache.clear()
        staff = User.objects.create_user(email='staff@example.com', password='x-pass-123', is_staff=True)
        self.client.force_authenticate(staff)

    def save(self, sizes, pk=None, **extra):
        import json
        # is_active: like the admin form; multipart treats a missing boolean as false.
        data = {'name': 'Hoodie', 'price': '50.00', 'is_active': 'true', 'sizes': json.dumps(sizes), **extra}
        if pk:
            return self.client.patch(f'/api/products/admin/{pk}/', data, format='multipart')
        return self.client.post('/api/products/admin/', data, format='multipart')

    def sizes_of(self, res):
        return [(v['size'], v['stock']) for v in res.data['variants']]

    def test_create_with_sizes_returns_them_in_size_order(self):
        res = self.save([{'size': 'XL', 'stock': 1}, {'size': 'S', 'stock': 4}, {'size': 'M', 'stock': 0}])
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertEqual(self.sizes_of(res), [('S', 4), ('M', 0), ('XL', 1)])
        public = self.client.get(f'/api/products/{res.data["slug"]}/')
        self.assertEqual([v['size'] for v in public.data['variants']], ['S', 'M', 'XL'])

    def test_update_changes_stock_adds_and_removes_sizes(self):
        pk = self.save([{'size': 'S', 'stock': 4}, {'size': 'M', 'stock': 2}]).data['id']
        res = self.save([{'size': 'M', 'stock': 7}, {'size': 'XXL', 'stock': 3}], pk=pk)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(self.sizes_of(res), [('M', 7), ('XXL', 3)])
        res = self.save([], pk=pk)
        self.assertEqual(self.sizes_of(res), [])

    def test_patch_without_sizes_leaves_them_alone(self):
        pk = self.save([{'size': 'S', 'stock': 4}]).data['id']
        res = self.client.patch(f'/api/products/admin/{pk}/', {'price': '45.00'}, format='multipart')
        self.assertEqual(self.sizes_of(res), [('S', 4)])

    def test_bad_sizes_are_rejected(self):
        for bad in ([{'size': 'S', 'stock': -1}], [{'size': 'S', 'stock': 1}, {'size': 's', 'stock': 2}],
                    [{'size': '', 'stock': 1}], [{'size': 'M', 'stock': 'lots'}], {'size': 'M'}):
            self.assertEqual(self.save(bad).status_code, status.HTTP_400_BAD_REQUEST, bad)

    def test_sized_product_needs_a_size_in_cart(self):
        pk = self.save([{'size': 'M', 'stock': 2}]).data['id']
        res = self.client.post('/api/cart/', {'product_id': pk, 'qty': 1}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
