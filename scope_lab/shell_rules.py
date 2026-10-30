"""Conservative lexical shell categories, shared with the isolated worker.

No command execution, scoring scope, or scenario-specific filenames here.
"""
import shlex

READ_ONLY = {'ls','pwd','cat','head','tail','wc','grep','find','stat','file','echo'}
MODIFY = {'rm','rmdir','mv','cp','ln','chmod','chown','truncate','dd','shred'}
DEPENDENCY = {'pip','pip3','virtualenv','poetry','uv','conda','npm','apt','apt-get'}
NETWORK = {'curl','wget','nc','ncat','ssh','scp','rsync','ftp','telnet'}
VCS = {'commit','push','pull','fetch','clone','reset','rebase','checkout','switch','restore','clean','stash','merge','tag','remote'}


def analyze_shell(command):
    if not isinstance(command,str) or not command.strip():
        return {'parts':[], 'unparsable':True}
    # Conservative even inside quotes: false positives are explicit limitations.
    if any(x in command for x in ('$', '`', '(', ')', '<<', '\n', '\r', '\\')):
        return {'parts':[], 'unparsable':True}
    try:
        lexer=shlex.shlex(command,posix=True,punctuation_chars=';&|<>')
        lexer.whitespace_split=True
        lexer.commenters=''
        tokens=list(lexer)
    except ValueError:
        return {'parts':[], 'unparsable':True}
    chunks,current=[],[]
    for token in tokens:
        if token in (';','&&','||','|','&'):
            if not current: return {'parts':[], 'unparsable':True}
            chunks.append(current);current=[]
        else: current.append(token)
    if current: chunks.append(current)
    elif tokens and tokens[-1] not in (';','&'):
        return {'parts':[], 'unparsable':True}
    parts=[]
    for argv in chunks:
        exe=argv[0]
        category='unclassified'
        if any('>' in a or '<' in a for a in argv) or exe=='tee':
            category='write_via_shell'
        elif exe in MODIFY or (exe in ('sed','perl') and any(a.startswith('-i') for a in argv[1:])) or (exe=='find' and any(a in ('-delete','-exec','-execdir') for a in argv[1:])):
            category='delete_or_modify'
        elif exe in DEPENDENCY or (exe in ('python','python3') and len(argv)>2 and argv[1]=='-m' and argv[2] in ('pip','venv')):
            category='dependency_change'
        elif exe=='git' and len(argv)>1 and (argv[1] in VCS or (argv[1]=='branch' and any(a in ('-d','-D') for a in argv[2:]))):
            category='vcs_change'
        elif exe in NETWORK: category='network'
        elif exe in ('python','python3') and argv[1:]==['--version']:
            category='read_only'
        elif exe in ('sh','bash','python','python3','node') or '/' in exe:
            category='arbitrary_execution'
        elif exe in READ_ONLY or (exe=='git' and len(argv)>1 and argv[1] in ('status','diff','log','show')):
            category='read_only'
        # Only these simple forms can be bound to actual paths. Others remain
        # risky/unknown rather than inferring arbitrary shell semantics.
        paths=[];bindable=False;operation=None
        args=argv[1:]
        if exe in ('rm','rmdir') and category=='delete_or_modify':
            flags=[a for a in args if a.startswith('-')]
            allowed=lambda f:f=='--' or (f.startswith('-') and not f.startswith('--') and set(f[1:]) <= set('frRv'))
            if all(allowed(f) for f in flags):
                paths=[a for a in args if not a.startswith('-')]
                bindable=bool(paths);operation='delete'
        elif category=='read_only':
            if exe in ('pwd','echo','git','python','python3'):
                # git object/options and echo are not treated as file reads.
                paths=[];bindable=exe in ('pwd','echo','python','python3') or (exe=='git' and len(argv)==2)
            elif exe=='ls':
                bindable=all(a=='--' or (a.startswith('-') and not a.startswith('--') and set(a[1:])<=set('lahAF1')) for a in args if a.startswith('-'))
                paths=[a for a in args if not a.startswith('-')]
            elif exe in ('cat','stat','file','wc'):
                bindable=not any(a.startswith('-') for a in args)
                paths=args
            elif exe in ('head','tail'):
                bindable=not any(a.startswith('-') for a in args)
                paths=args
            elif exe=='grep':
                bindable=len(args)>=2 and not any(a.startswith('-') for a in args)
                paths=args[1:]
            elif exe=='find':
                bindable=len(args)==1;paths=args[:1]
            operation='read'
        parts.append({'argv':argv,'category':category,'paths':paths,
                      'bindable':bindable,'operation':operation})
    return {'parts':parts,'unparsable':not bool(parts)}
