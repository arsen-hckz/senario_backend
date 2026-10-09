import os

from django.core.management.base import BaseCommand

from moodboard.image_utils import optimize_image_file
from moodboard.models import MoodboardPhoto
from products.models import ProductImage


class Command(BaseCommand):
    help = (
        'Downsize and recompress stored moodboard and product photos that were '
        'uploaded before automatic optimization (or through a path that skipped it). '
        'Safe to re-run: photos that are already small are left alone.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Report savings without changing any file.')

    def handle(self, *args, dry_run=False, **options):
        total_before = total_after = processed = 0

        querysets = [
            ('moodboard', MoodboardPhoto.objects.exclude(image='').exclude(image__isnull=True)),
            ('product', ProductImage.objects.exclude(image='')),
        ]
        for label, photos in querysets:
            for photo in photos:
                name = photo.image.name
                storage = photo.image.storage

                if not storage.exists(name):
                    self.stderr.write(self.style.WARNING(f'Skipping {label} photo {photo.pk}: file missing ({name})'))
                    continue

                before_size = storage.size(name)
                with photo.image.open('rb') as f:
                    optimized = optimize_image_file(f, name=os.path.basename(name))
                after_size = optimized.size

                if after_size >= before_size * 0.9:
                    continue

                if not dry_run:
                    # Delete first so the storage backend reuses the same name/URL
                    # instead of appending a suffix for a "new" file.
                    storage.delete(name)
                    photo.image.save(os.path.basename(name), optimized, save=True)

                total_before += before_size
                total_after += after_size
                processed += 1
                self.stdout.write(f'{label} photo {photo.pk}: {before_size // 1024}KB -> {after_size // 1024}KB')

        if processed:
            verb = 'Would optimize' if dry_run else 'Optimized'
            self.stdout.write(self.style.SUCCESS(
                f'{verb} {processed} photo(s): {total_before // 1048576}MB -> {total_after // 1048576}MB'
            ))
        else:
            self.stdout.write('No photos needed optimization.')
