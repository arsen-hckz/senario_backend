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
        if instance.image:
            request = self.context.get('request')
            url = instance.image.url
            data['src'] = request.build_absolute_uri(url) if request else url
        else:
            data['src'] = instance.external_src
        return data
