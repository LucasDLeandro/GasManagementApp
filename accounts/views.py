from django.shortcuts import render

from rest_framework import viewsets, status
from rest_framework.response import Response
from .models import User, UserProfile, DadosTrabalhistas
from .serializers import UserSerializer

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer()
