from rest_framework import serializers

from .image_utils import optimize_image_file
from .models import MoodboardPhoto


class MoodboardPhotoSerializer(serializers.ModelSerializer):
    # Write-only inputs: either an uploaded file (`image`) or a reused asset
    # path/URL (`src`, stored on the model as `external_src`). `to_representation`
    # below collapses whichever was set back down into a single `src` output field.
    image = serializers.ImageField(write_only=True, required=False, allow_null=True)
    src   = serializers.CharField(write_only=True, required=False, allow_blank=True, source='external_src')

    class Meta:
        model = MoodboardPhoto
        fields = ('id', 'title', 'body', 'order', 'image', 'src')
        read_only_fields = ('order',)

    def validate_image(self, value):
        return optimize_image_file(value, name=value.name)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')

        def absolute(field_file):
            return request.build_absolute_uri(field_file.url) if request else field_file.url

        if instance.image:
            data['src'] = absolute(instance.image)
        else:
            data['src'] = instance.external_src
        # Small version for grid tiles; `src` stays the full photo for the viewer.
        data['thumb'] = absolute(instance.thumb) if instance.thumb else data['src']
        return data
