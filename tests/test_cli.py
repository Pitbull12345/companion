from companion.cli import main


def test_main(capsys):
    main()

    output = capsys.readouterr().out

    assert "Companion 0.1" in output
