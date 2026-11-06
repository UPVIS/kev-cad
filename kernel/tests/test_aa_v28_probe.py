import locale
def test_lib3mf_stellt_um(tmp_path):
    from build123d import Box, Mesher
    m = Mesher()
    m.add_shape(Box(10, 10, 10))
    m.write(str(tmp_path / "a.3mf"))
    assert locale.getencoding() == "US-ASCII"
