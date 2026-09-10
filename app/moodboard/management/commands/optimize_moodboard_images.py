import os

from django.core.management.base import BaseCommand

from moodboard.image_utils import optimize_image_file
from moodboard.models import MoodboardPhoto


class Command(BaseCommand):
    help = 'Re-downsize and recompress moodboard photos uploaded before image optimization was added.'

    def handle(self, *args, **options):
        photos = MoodboardPhoto.objects.exclude(image='').exclude(image__isnull=True)
        processed = 0
        total_before = 0
        total_after = 0

        for photo in photos:
            name = photo.image.name
            storage = photo.image.storage

            if not storage.exists(name):
                self.stderr.write(self.style.WARNING(f'Skipping photo {photo.pk}: file missing ({name})'))
                continue

            before_size = storage.size(name)
            with photo.image.open('rb') as f:
                optimized = optimize_image_file(f, name=os.path.basename(name))
            after_size = optimized.size

            if after_size >= before_size:
                self.stdout.write(f'Photo {photo.pk}: already optimal ({before_size // 1024}KB), skipping')
                continue

            # Delete first so the storage backend reuses the same name/URL
            # instead of appending a suffix for a "new" file.
            storage.delete(name)
            photo.image.save(os.path.basename(name), optimized, save=True)

            total_before += before_size
            total_after += after_size
            processed += 1
            self.stdout.write(f'Photo {photo.pk}: {before_size // 1024}KB -> {after_size // 1024}KB')

        if processed:
            saved = total_before - total_after
            self.stdout.write(self.style.SUCCESS(
                f'Optimized {processed} photo(s), saved {saved // 1024}KB total '
                f'({total_before // 1024}KB -> {total_after // 1024}KB)'
            ))
        else:
            self.stdout.write('No photos needed optimization.')
