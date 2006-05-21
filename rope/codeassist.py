import compiler
import inspect
import __builtin__

from rope.exceptions import RopeException


class RopeSyntaxError(RopeException):
    pass


class CompletionProposal(object):
    """A completion proposal.
    
    The kind instance variable shows the type of the completion and
    can be global_variable, function, class
    
    """
    def __init__(self, completion, kind):
        self.completion = completion
        self.kind = kind


class CompletionResult(object):
    """A completion result.
    
    Attribute:
    proposals -- A list of CompletionProposals
    start_offset -- completion start offset
    end_offset -- completion end offset
    
    """
    def __init__(self, proposals=[], start_offset=0, end_offset=0):
        self.proposals = proposals
        self.start_offset = start_offset
        self.end_offset = end_offset


class _Scope(object):
    def __init__(self, lineno, var_dict, children):
        self.lineno = lineno
        self.var_dict = var_dict
        self.children = children


class _FunctionScopeVisitor(object):
    def __init__(self, starting, start_line):
        self.starting = starting
        self.scope = _Scope(start_line, {}, [])

    def visitImport(self, node):
        for import_pair in node.names:
            name, alias = import_pair
            imported = name
            if alias is not None:
                imported = alias
            if imported.startswith(self.starting):
                self.scope.var_dict[imported] = CompletionProposal(imported, 'module')

    def visitAssName(self, node):
        if node.name.startswith(self.starting):
            self.scope.var_dict[node.name] = CompletionProposal(node.name, 'local_variable')
        

    def visitFunction(self, node):
        if node.name.startswith(self.starting):
            self.scope.var_dict[node.name] = CompletionProposal(node.name, 'function')
        new_visitor = _FunctionScopeVisitor(self.starting, node)
        compiler.walk(node, new_visitor)
        self.scope.children.append(new_visitor.scope)

    def visitClass(self, node):
        if node.name.startswith(self.starting):
            self.result[node.name] = CompletionProposal(node.name, 'class')
        new_visitor = _ClassScopeVisitor(self.starting, node)
        compiler.walk(node, new_visitor)
        self.scope.children.append(new_visitor.scope)

    @staticmethod
    def walk_function(starting, function_node):
        new_visitor = _FunctionScopeVisitor(starting, function_node.lineno)
        for node in function_node.getChildNodes():
            compiler.walk(node, new_visitor)
        return new_visitor


class _ClassScopeVisitor(object):
    def __init__(self, starting, start_line):
        self.starting = starting
        self.scope = _Scope(start_line, {}, [])

    def visitImport(self, node):
        pass

    def visitAssName(self, node):
        pass

    def visitFunction(self, node):
        new_visitor = _FunctionScopeVisitor.walk_function(self.starting, node)
        self.scope.children.append(new_visitor.scope)

    def visitClass(self, node):
        new_visitor = _ClassScopeVisitor.walk_class(self.starting, node)
        self.scope.children.append(new_visitor.scope)

    @staticmethod
    def walk_class(starting, class_node):
        new_visitor = _ClassScopeVisitor(starting, class_node.lineno)
        for node in class_node.getChildNodes():
            compiler.walk(node, new_visitor)
        return new_visitor


class _GlobalScopeVisitor(object):
    
    def __init__(self, starting):
        self.starting = starting
        self.scope = _Scope(0, {}, [])

    def visitImport(self, node):
        for import_pair in node.names:
            name, alias = import_pair
            imported = name
            if alias is not None:
                imported = alias
            if imported.startswith(self.starting):
                self.scope.var_dict[imported] = CompletionProposal(imported, 'module')

    def visitAssName(self, node):
        if node.name.startswith(self.starting):
            self.scope.var_dict[node.name] = CompletionProposal(node.name, 'global_variable')
        

    def visitFunction(self, node):
        if node.name.startswith(self.starting):
            self.scope.var_dict[node.name] = CompletionProposal(node.name, 'function')
        new_visitor = _FunctionScopeVisitor.walk_function(self.starting, node)
        self.scope.children.append(new_visitor.scope)

    def visitClass(self, node):
        if node.name.startswith(self.starting):
            self.scope.var_dict[node.name] = CompletionProposal(node.name, 'class')
        new_visitor = _ClassScopeVisitor.walk_class(self.starting, node)
        self.scope.children.append(new_visitor.scope)


class ICodeAssist(object):
    def complete_code(self, source, offset):
        pass


class NoAssist(ICodeAssist):
    def complete_code(self, source_code, offset):
        return CompletionResult()


class CodeAssist(ICodeAssist):
    def __init__(self):
        self.builtins = [str(name) for name in dir(__builtin__)
                         if not name.startswith('_')]
        import keyword
        self.keywords = keyword.kwlist

    def _find_starting_offset(self, source_code, offset):
        current_offset = offset - 1
        while current_offset >= 0 and (source_code[current_offset].isalnum() or
                                       source_code[current_offset] in '_.'):
            current_offset -= 1;
        return current_offset + 1

    def _comment_current_line(self, source_code, offset):
        line_beginning = offset - 1
        while line_beginning >= 0 and source_code[line_beginning] != '\n':
            line_beginning -= 1
        line_ending = offset
        while line_ending < len(source_code) and source_code[line_ending] != '\n':
            line_ending += 1
        result = source_code
        if line_beginning != -1 and line_beginning < line_ending - 1:
            result = source_code[:line_beginning] + '#' + source_code[line_beginning + 2:]
        return result
    
    def _get_matching_builtins(self, starting):
        result = {}
        for builtin in self.builtins:
            if builtin.startswith(starting):
                obj = getattr(__builtin__, builtin)
                kind = 'unknown'
                if inspect.isclass(obj):
                    kind = 'class'
                if inspect.isbuiltin(obj):
                    kind = 'builtin_function'
                if inspect.ismodule(obj):
                    kind = 'module'
                if inspect.ismethod(obj):
                    kind = 'method'
                if inspect.isfunction(obj):
                    kind = 'function'
                result[builtin] = CompletionProposal(builtin, kind)
        return result

    def _get_matching_keywords(self, starting):
        result = {}
        for kw in self.keywords:
            if kw.startswith(starting):
                result[kw] = CompletionProposal(kw, 'keyword')
        return result

    def _get_all_completions(self, global_scope, lineno):
        result = {}
        current_scope = global_scope
        while current_scope is not None:
            result.update(current_scope.var_dict)
            new_scope = None
            for scope in current_scope.children:
                if scope.lineno < lineno:
                    new_scope = scope
                else:
                    break
            current_scope = new_scope
        return result
    
    def _get_line_number(self, source_code, offset):
        return source_code[:offset].count('\n') + 1

    def complete_code(self, source_code, offset):
        if offset > len(source_code):
            return []
        starting_offset = self._find_starting_offset(source_code, offset)
        starting = source_code[starting_offset:offset]
        commented_source_code = self._comment_current_line(source_code, offset)
        try:
            code_ast = compiler.parse(commented_source_code)
        except SyntaxError, e:
            raise RopeSyntaxError(e)
        visitor = _GlobalScopeVisitor(starting)
        compiler.walk(code_ast, visitor)
#        result.update(visitor.scope.var_dict)
        result = self._get_all_completions(visitor.scope,
                                           self._get_line_number(source_code, offset))
        if len(starting) > 0:
            result.update(self._get_matching_builtins(starting))
            result.update(self._get_matching_keywords(starting))
        return CompletionResult(result.values(), starting_offset, offset)

