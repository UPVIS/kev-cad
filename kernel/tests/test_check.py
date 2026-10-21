from kevcad_kernel.cli import check


def test_check_runs(capsys):
    assert check() == 0
    out = capsys.readouterr().out
    assert "build123d 0.13" in out
    assert "12 Dreiecke, 6 Flächen" in out
