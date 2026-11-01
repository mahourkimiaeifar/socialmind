from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("studio/", views.studio_index, name="studio_index"),
    path("studio/new/", views.studio_new, name="studio_new"),
    path("studio/<int:pk>/", views.conversation_detail, name="conversation_detail"),
    path("studio/<int:pk>/message/", views.conversation_message, name="conversation_message"),
    path("studio/<int:pk>/generate/", views.conversation_generate, name="conversation_generate"),
    path("studio/<int:pk>/brief/", views.conversation_update_brief, name="conversation_update_brief"),
    path("studio/<int:pk>/delete/", views.conversation_delete, name="conversation_delete"),
    path("help/", views.help_view, name="help"),
    path("health/", views.health, name="health"),
]
