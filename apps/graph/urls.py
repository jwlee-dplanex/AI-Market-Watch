from django.urls import path
from . import views

urlpatterns = [
    path("", views.graph, name="graph"),
    path("orgs/<int:pk>/panel/", views.graph_org_panel, name="graph_org_panel"),
]
