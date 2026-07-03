def test_ast_class_is_named_astnode():
    from md2html.parser import ASTNode  # noqa: F401 -- ImportError before the rename
    import md2html.parser as parser_module
    assert not hasattr(parser_module, "Node"), "old name Node should be retired"
