"""Read the GOAT input header with explicit preprocessor defines.

Not a general MQL compiler: unsupported conditional directives/enum expressions
fail rather than silently manufacturing a schema. Dependencies need a separate
logic audit; source declarations alone do not prove an optimization axis active.
"""
import hashlib
import re

# MetaQuotes, MQL5 Programming for Traders, section 5.5, p.789.
# https://www.mql5.com/files/book/mql5book.pdf
BUILTIN_ENUMS = {'ENUM_MA_METHOD': {
    'MODE_SMA': 0, 'MODE_EMA': 1, 'MODE_SMMA': 2, 'MODE_LWMA': 3}}


def discover(raw, defines):
    text = raw.decode('utf-8-sig')
    # Retain quoted strings; remove comments, including commented-out inputs.
    token = r'"(?:\\.|[^"\\])*"|/\*[\s\S]*?\*/|//[^\n]*'
    text = re.sub(token,lambda m: m[0] if m[0].startswith('"') else '\n'*m[0].count('\n'),text)
    macros = dict(defines)
    active, stack, lines = True, [], []
    for line in text.splitlines():
        directive = re.match(r'\s*#(\w+)\s*(.*)',line)
        if directive:
            op, arg = directive.groups()
            if op in ('ifdef','ifndef'):
                branch = arg.strip() in macros
                if op == 'ifndef': branch = not branch
                stack.append((active,branch,False)); active = active and branch
            elif op == 'else':
                if not stack or stack[-1][2]: raise ValueError('Malformed else')
                parent,branch,_ = stack[-1]; stack[-1]=(parent,branch,True)
                active = parent and not branch
            elif op == 'endif':
                if not stack: raise ValueError('Unmatched endif')
                active = stack.pop()[0]
            elif op == 'define' and active:
                parts=arg.split(None,1); macros[parts[0]]=parts[1] if len(parts)>1 else ''
            elif op in ('if','elif','include','undef'):
                raise ValueError('Unsupported input-header directive: '+op)
            continue
        if active: lines.append(line)
    if stack: raise ValueError('Unclosed conditional')
    text='\n'.join(lines)
    constants={label:value for choices in BUILTIN_ENUMS.values() for label,value in choices.items()}
    def integer(expr,seen=()):
        expr=expr.strip()
        if re.fullmatch(r'-?\d+',expr): return int(expr)
        if expr in constants:return constants[expr]
        if expr in macros and expr not in seen:return integer(macros[expr],seen+(expr,))
        raise ValueError('Unresolved enum expression: '+expr)
    enums={name:dict(choices) for name,choices in BUILTIN_ENUMS.items()}
    for match in re.finditer(r'\benum\s+(\w+)\s*\{([^}]+)\}',text):
        name,body=match.groups(); choices={}; previous=-1
        if name in enums: raise ValueError('Duplicate enum: '+name)
        for item in body.split(','):
            if not item.strip():continue
            parts=item.strip().split('=',1); label=parts[0].strip()
            if not re.fullmatch(r'\w+',label):raise ValueError('Malformed enum member')
            if label in constants: raise ValueError('Duplicate enum member: '+label)
            number=integer(parts[1]) if len(parts)==2 else previous+1
            choices[label]=number; constants[label]=number; previous=number
        enums[name]=choices
    inputs={}
    pattern=r'\b(input|sinput)\s+(\w+)\s+(\w+)\s*=\s*((?:"(?:\\.|[^"\\])*"|[^;])+);'
    for match in re.finditer(pattern,text):
        kind,type_name,name,default=match.groups()
        if name in inputs:raise ValueError('Duplicate input: '+name)
        if type_name not in enums and type_name not in {'bool','int','long','double','string','datetime','color','uint','ulong','float'}:
            raise ValueError('Unknown input type: '+type_name)
        inputs[name]=dict(type=type_name, declaration=kind, default_expression=default.strip(),
                          optimizable=kind=='input' and type_name!='string',
                          enum_choices=enums.get(type_name),dependency_audited=False)
    declaration_text=re.sub(r'"(?:\\.|[^"\\])*"','""',text)
    declarations=sum(type_name!='group' for type_name in
                     re.findall(r'\b(?:input|sinput)\s+(\w+)',declaration_text))
    if declarations != len(inputs):raise ValueError('Unparsed input declaration')
    return dict(schema_version=1,source_sha256=hashlib.sha256(raw).hexdigest(),
                defines=dict(defines),inputs=inputs,scope='provided_input_header',
                builtin_enum_reference='https://www.mql5.com/files/book/mql5book.pdf#page=789',
                execution_ready=False)
