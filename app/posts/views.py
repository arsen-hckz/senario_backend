from django.db.models import Max
from rest_framework import generics, permissions, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import SalePost
from .serializers import SalePostSerializer


class SalePostListView(generics.ListAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = SalePostSerializer
    pagination_class = None
    # Posts for hidden products are left out, or the nav would show "Sale"
    # linking to an empty page.
    queryset = SalePost.objects.filter(product__is_active=True).select_related('product')


class SalePostAdminViewSet(viewsets.ModelViewSet):
    permission_classes = (permissions.IsAdminUser,)
    serializer_class = SalePostSerializer
    queryset = SalePost.objects.all().select_related('product')
    lookup_field = 'pk'
    pagination_class = None

    def perform_create(self, serializer):
        max_order = SalePost.objects.aggregate(m=Max('order'))['m']
        serializer.save(order=0 if max_order is None else max_order + 1)


class SalePostReorderView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request):
        order = request.data.get('order')
        if not isinstance(order, list):
            return Response({'detail': 'order must be a list of post ids.'}, status=status.HTTP_400_BAD_REQUEST)

        posts = {str(post.id): post for post in SalePost.objects.all()}
        to_update = []
        for index, post_id in enumerate(order):
            post = posts.get(str(post_id))
            if post is None:
                continue
            post.order = index
            to_update.append(post)
        SalePost.objects.bulk_update(to_update, ['order'])

        serializer = SalePostSerializer(SalePost.objects.all().select_related('product'), many=True)
        return Response(serializer.data)
