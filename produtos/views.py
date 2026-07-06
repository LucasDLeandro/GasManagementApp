from rest_framework import viewsets
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from rest_framework.permissions import IsAuthenticated

from .models import Produto
from .serializers import ProdutoSerializer

class ProdutoViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows produtos to be viewed or edited.
    """
    queryset = Produto.objects.all()
    serializer_class = ProdutoSerializer
    # permission_classes = [IsAuthenticated] # Podemos descomentar se houver auth estrita

class ProdutoTemplateView(LoginRequiredMixin, TemplateView):
    """
    View to render the Produto frontend page with modal.
    """
    template_name = 'produtos/index.html'

