def test_gtk_frontend_imports_without_opening_a_display() -> None:
    from companion.frontend import gtk

    assert gtk.GtkPetApplication is not None
    assert gtk.PetWindow is not None
