from django.shortcuts import redirect
from django.urls import reverse
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

class ForcePasswordChangeMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if not request.user.is_authenticated:
            return None

        # Verificar se o usuário precisa trocar a senha
        if getattr(request.user, 'force_password_change', False):
            path = request.path_info

            # Rotas permitidas para quem precisa trocar a senha
            try:
                change_password_url = reverse('accounts:change_password')
            except:
                change_password_url = '/accounts/change-password/'

            allowed_paths = [
                change_password_url,
                '/accounts/logout/',
                '/admin/logout/',
                '/accounts/api/login/',
                '/api/token/refresh/',
            ]

            for allowed in allowed_paths:
                if path.startswith(allowed):
                    return None

            if path.startswith('/static/') or path.startswith('/media/'):
                return None

            # Se for chamada API, retorna erro 403 JSON
            if path.startswith('/api/') or '/api/' in path:
                return JsonResponse(
                    {'detail': 'Você precisa alterar sua senha padrão antes de continuar.', 'force_password_change': True}, 
                    status=403
                )

            # Redireciona a navegação HTML
            return redirect(change_password_url)
