from django.db.models import Max
from rest_framework import generics, permissions, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import MoodboardPhoto
from .serializers import MoodboardPhotoSerializer


class MoodboardListView(generics.ListAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = MoodboardPhotoSerializer
    queryset = MoodboardPhoto.objects.all()
    pagination_class = None


class MoodboardAdminViewSet(viewsets.ModelViewSet):
    permission_classes = (permissions.IsAdminUser,)
    serializer_class = MoodboardPhotoSerializer
    queryset = MoodboardPhoto.objects.all()
    lookup_field = 'pk'
    pagination_class = None

    def perform_create(self, serializer):
        max_order = MoodboardPhoto.objects.aggregate(m=Max('order'))['m']
        serializer.save(order=0 if max_order is None else max_order + 1)


class MoodboardReorderView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request):
        order = request.data.get('order')
        if not isinstance(order, list):
            return Response(
                {'detail': 'order must be a list of photo ids.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        photos = {photo.id: photo for photo in MoodboardPhoto.objects.filter(id__in=order)}
        to_update = []
        for index, photo_id in enumerate(order):
            photo = photos.get(photo_id)
            if photo is None:
                continue
            photo.order = index
            to_update.append(photo)

        MoodboardPhoto.objects.bulk_update(to_update, ['order'])

        serializer = MoodboardPhotoSerializer(
            MoodboardPhoto.objects.all(), many=True, context={'request': request}
        )
        return Response(serializer.data)
