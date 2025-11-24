from django.urls import path
from .views import (
    FileAssociationCreateView, CSVUploadView, 
    FileAssociationUpdateView, FileAssociationDeleteView,
    GlobalAlertCreateView, GlobalAlertUpdateView,
    GlobalAlertDeleteView, GlobalAlertListView
)
from .regular_user_views import(
    CSVListView, FilterCSVView,
    CSVHeaderView, SortCSVView,
    FavoriteRowView, CustomAlertCreateView,
    CustomAlertUpdateView, CustomAlertDeleteView,
    UserSettingsView, UpdateUserSettingsView,
)

urlpatterns = [
    path('file-associations/create/', FileAssociationCreateView.as_view(), name='fa-create'),
    path('file-associations/<int:fa_id>/upload/', CSVUploadView.as_view(), name='fa-upload'),
    path('file-associations/update/<int:fa_id>/', FileAssociationUpdateView.as_view(), name='fa-update'),
    path('file-associations/delete/<int:fa_id>/', FileAssociationDeleteView.as_view(), name='fa-delete'),
    path('global-alert/create/<int:pk>/', GlobalAlertCreateView.as_view(), name='ga-create'),
    path('global-alert/update/<int:pk>/', GlobalAlertUpdateView.as_view(), name='ga-update'),
    path('global-alert/delete/<int:pk>/', GlobalAlertDeleteView.as_view(), name='ga-delete'),
    path('global-alert/all/', GlobalAlertListView.as_view(), name='ga-all'),
    path('csv-data/<int:fa_id>/', CSVListView.as_view(), name='csv-data'),
    path('filter-csv/<int:fa_id>/', FilterCSVView.as_view(), name='filter-csv'),
    path('csv-headers/<int:fa_id>/', CSVHeaderView.as_view(), name='csv-headers'),
    path('sort-csv/<int:fa_id>/', SortCSVView.as_view(), name='sort-csv'),
    path('fav-row/<int:fa_id>/', FavoriteRowView.as_view(), name='fav-row'),
    path('custom-alert/create/<int:pk>/', CustomAlertCreateView.as_view(), name='ca-create'),
    path('custom-alert/update/<int:id>/', CustomAlertUpdateView.as_view(), name='ca-update'),
    path('settings/create/<int:pk>/', UserSettingsView.as_view(), name='create-settings'),
    path('settings/update/<int:pk>/', UpdateUserSettingsView.as_view(), name='update-settings'),
    # path('test-email/', TestEmail.as_view(), name='test-email'),
]
