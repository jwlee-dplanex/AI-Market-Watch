from django.urls import path
from . import views

urlpatterns = [
    path("", views.graph, name="graph"),
    path("orgs/<int:pk>/panel/", views.graph_org_panel, name="graph_org_panel"),
    path("edges/<int:pk_a>/<int:pk_b>/panel/", views.graph_edge_panel, name="graph_edge_panel"),
]
