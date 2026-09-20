"""Generate Pydantic model source from a ``Config`` schema."""

from __future__ import annotations

import enum
import inspect
import json
import keyword
import pathlib
import re
import textwrap
import types
import typing
from dataclasses import dataclass, field
from typing import Any, cast

from kwconf.annotations import choices_from_annotation
from kwconf.config import Config
from kwconf.util.util_misc import NoParam
from kwconf.value import _Value as Value


@dataclass
class _ImportState:
    modules: set[str] = field(default_factory=set)
    pydantic_names: set[str] = field(
        default_factory=lambda: {'BaseModel', 'Field'}
    )


class _RenderError(ValueError):
    pass


def _module_expr(module_name: str, qualname: str, state: _ImportState) -> str:
    if module_name == 'builtins':
        return qualname
    state.modules.add(module_name)
    return f'{module_name}.{qualname}'


def _render_type(annotation: Any, state: _ImportState) -> str:
    """Render a runtime annotation as executable Python source."""
    if annotation is Any or annotation is typing.Any:
        return 'typing.Any'
    if annotation is None or annotation is type(None):
        return 'None'
    if isinstance(annotation, str):
        return repr(annotation)
    if isinstance(annotation, typing.ForwardRef):
        return repr(annotation.__forward_arg__)

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    if origin in {typing.Union, types.UnionType}:
        return ' | '.join(_render_type(arg, state) for arg in args)
    if origin is typing.Literal:
        values = ', '.join(_render_value(arg, state) for arg in args)
        return f'typing.Literal[{values}]'
    if origin is typing.Annotated:
        base = _render_type(args[0], state)
        metadata = ', '.join(_render_value(arg, state) for arg in args[1:])
        return f'typing.Annotated[{base}, {metadata}]'

    if origin is not None:
        origin_expr = _render_type(origin, state)
        if not args:
            return origin_expr
        arg_text = ', '.join(
            '...' if arg is Ellipsis else _render_type(arg, state)
            for arg in args
        )
        return f'{origin_expr}[{arg_text}]'

    if isinstance(annotation, type):
        if issubclass(annotation, pathlib.PurePath):
            state.modules.add('pathlib')
            public_name = annotation.__name__
            if getattr(pathlib, public_name, None) is annotation:
                return f'pathlib.{public_name}'
            return 'pathlib.Path'
        return _module_expr(
            annotation.__module__, annotation.__qualname__, state
        )

    module_name = getattr(annotation, '__module__', None)
    qualname = getattr(annotation, '__qualname__', None)
    if module_name and qualname:
        return _module_expr(module_name, qualname, state)

    raise _RenderError(f'Cannot render annotation {annotation!r}')


def _render_value(value: Any, state: _ImportState) -> str:
    """Render a common configuration default as executable Python source."""
    if value is None or isinstance(value, (bool, int, str)):
        return repr(value)
    if isinstance(value, float):
        if value == float('inf'):
            return "float('inf')"
        if value == float('-inf'):
            return "float('-inf')"
        if value != value:
            return "float('nan')"
        return repr(value)
    if isinstance(value, pathlib.Path):
        state.modules.add('pathlib')
        return f'pathlib.Path({str(value)!r})'
    if isinstance(value, enum.Enum):
        cls = type(value)
        cls_expr = _module_expr(cls.__module__, cls.__qualname__, state)
        return f'{cls_expr}.{value.name}'
    if isinstance(value, list):
        return '[' + ', '.join(_render_value(v, state) for v in value) + ']'
    if isinstance(value, tuple):
        body = ', '.join(_render_value(v, state) for v in value)
        if len(value) == 1:
            body += ','
        return f'({body})'
    if isinstance(value, dict):
        body = ', '.join(
            f'{_render_value(k, state)}: {_render_value(v, state)}'
            for k, v in value.items()
        )
        return '{' + body + '}'
    if isinstance(value, set):
        if not value:
            return 'set()'
        body = ', '.join(
            sorted(_render_value(v, state) for v in value)
        )
        return '{' + body + '}'
    if isinstance(value, frozenset):
        if not value:
            return 'frozenset()'
        body = ', '.join(
            sorted(_render_value(v, state) for v in value)
        )
        return f'frozenset({{{body}}})'

    cls = type(value)
    if cls.__module__ == 'builtins':
        raise _RenderError(f'Cannot render default value {value!r}')

    # A few stdlib/user value types have executable reprs once their module is
    # imported (datetime/date/time/timedelta, Decimal, UUID, simple named
    # constructors, etc.). Do not trust reprs that are not expression-shaped.
    representation = repr(value)
    if re.match(r'^[A-Za-z_][A-Za-z0-9_.]*\(.*\)$', representation, re.S):
        state.modules.add(cls.__module__)
        head = representation.split('(', 1)[0]
        if '.' not in head:
            representation = f'{cls.__module__}.{representation}'
        return representation

    raise _RenderError(f'Cannot render default value {value!r}')


def _render_factory(factory: Any, state: _ImportState) -> str:
    module_name = getattr(factory, '__module__', None)
    qualname = getattr(factory, '__qualname__', None)
    if (
        not module_name
        or not qualname
        or module_name == '__main__'
        or '<' in qualname
    ):
        raise _RenderError(
            'default_factory must be an importable named callable, got '
            f'{factory!r}'
        )
    if not (
        inspect.isclass(factory)
        or inspect.isfunction(factory)
        or inspect.isbuiltin(factory)
    ):
        raise _RenderError(
            'default_factory must be an importable function or class, got '
            f'{factory!r}'
        )
    return _module_expr(module_name, qualname, state)


def _json_compatible(value: Any) -> bool:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return False
    else:
        return True


def _normalize_aliases(alias: Any) -> list[str]:
    if alias is None:
        return []
    if isinstance(alias, str):
        return [alias]
    return list(alias)


def _infer_annotation(
    template: Value, state: _ImportState
) -> tuple[str, str | None]:
    annotation = getattr(template, '_annotation', None)
    if annotation is not None:
        try:
            return _render_type(annotation, state), None
        except _RenderError as ex:
            note = f'annotation {annotation!r} was not rendered: {ex}'
            return 'typing.Any', note

    if getattr(template, '_user_gave_type', False) and isinstance(
        template.type, type
    ):
        return (
            _render_type(template.type, state),
            'annotation inferred from deprecated kwconf type= metadata',
        )

    if template.default_factory is not None:
        factory = template.default_factory
        if isinstance(factory, type):
            try:
                return (
                    _render_type(factory, state),
                    'annotation inferred from default_factory',
                )
            except _RenderError:
                pass
        return 'typing.Any', 'field has no annotation; generated as typing.Any'

    default = template.value
    if default is not None:
        inferred = type(default)
        try:
            return (
                _render_type(inferred, state),
                'annotation inferred from the kwconf default',
            )
        except _RenderError:
            pass
    return 'typing.Any', 'field has no annotation; generated as typing.Any'


def _short_repr(value: Any) -> str:
    text = repr(value)
    if len(text) > 100:
        text = text[:97] + '...'
    return text


def _review_lines(note: str, indent: str = '    ') -> list[str]:
    label = 'REVIEW(kwconf-port): '
    initial = f'{indent}# {label}'
    subsequent = f'{indent}# ' + ' ' * len(label)
    wrapped = textwrap.wrap(
        note,
        width=79,
        initial_indent=initial,
        subsequent_indent=subsequent,
        break_long_words=False,
        break_on_hyphens=False,
    )
    return wrapped or [initial.rstrip()]


def _field_lines(
    key: str,
    annotation_expr: str,
    *,
    field_kwargs: list[str] | None = None,
    default_expr: str | None = None,
    required: bool = False,
) -> list[str]:
    if not key.isidentifier() or keyword.iskeyword(key):
        raise ValueError(
            f'Cannot port field {key!r}: Pydantic model fields must be valid '
            'Python identifiers. Rename the kwconf field or port it manually '
            'with a validation alias.'
        )

    field_kwargs = list(field_kwargs or [])
    prefix = f'    {key}: {annotation_expr}'
    if required and not field_kwargs:
        return [prefix]

    if field_kwargs:
        if default_expr is not None:
            field_kwargs.insert(0, f'default={default_expr}')
        compact = prefix + ' = Field(' + ', '.join(field_kwargs) + ')'
        if len(compact) <= 88:
            return [compact]
        lines = [prefix + ' = Field(']
        lines.extend(f'        {item},' for item in field_kwargs)
        lines.append('    )')
        return lines

    if default_expr is None:
        raise AssertionError('non-required field must have a default expression')
    return [prefix + f' = {default_expr}']


def _field_review_notes(key: str, template: Value) -> list[str]:
    notes = []
    parser_spec = getattr(template, '_parser_spec', None)
    if parser_spec is not None:
        notes.append(
            'custom/text parser semantics were not translated: '
            f'parser={_short_repr(parser_spec)}'
        )
    elif getattr(template, '_user_gave_type', False):
        notes.append(
            'deprecated kwconf type= also controlled text parsing; only its '
            'type-like schema information was ported'
        )

    choices = template.parsekw.get('choices')
    annotation = getattr(template, '_annotation', None)
    annotation_choices = choices_from_annotation(annotation)
    if choices is not None and tuple(choices) != tuple(annotation_choices or ()):
        notes.append(
            'CLI choices were not translated to a Pydantic constraint: '
            f'choices={_short_repr(choices)}'
        )

    cli_parts = []
    if template.position is not None:
        cli_parts.append(f'position={template.position!r}')
    if template.isflag == 'counter':
        cli_parts.append("isflag='counter'")
    if template.parsekw.get('nargs') is not None:
        cli_parts.append(f"nargs={template.parsekw['nargs']!r}")
    if template.bare is not NoParam:
        cli_parts.append(f'bare={template.bare!r}')
    if template.short_alias:
        cli_parts.append(f'short_alias={template.short_alias!r}')
    if template.group is not None:
        cli_parts.append(f'group={template.group!r}')
    if template.mutex_group is not None:
        cli_parts.append(f'mutex_group={template.mutex_group!r}')
    if cli_parts:
        notes.append(
            'CLI-only metadata was not translated: ' + ', '.join(cli_parts)
        )

    if template.validate is not None:
        notes.append(
            'kwconf validate= policy was not translated: '
            f'validate={template.validate!r}'
        )

    if template.tags is not None and not _json_compatible(template.tags):
        notes.append(
            f'tags for {key!r} were not JSON-compatible and were not '
            f'translated: {_short_repr(template.tags)}'
        )
    return notes


@dataclass
class _ClassSpec:
    config_cls: type[Config]
    generated_name: str
    field_name_map: dict[str, str] = field(default_factory=dict)


class _PydanticSourcePorter:
    def __init__(self) -> None:
        self.state = _ImportState()
        self.class_specs: dict[type[Config], _ClassSpec] = {}
        self.used_names: set[str] = set()
        self.class_order: list[type[Config]] = []

    def _unique_name(
        self, config_cls: type[Config], hint: str | None = None
    ) -> str:
        base = config_cls.__name__
        if base not in self.used_names:
            self.used_names.add(base)
            return base
        if hint:
            clean_hint = ''.join(
                part[:1].upper() + part[1:]
                for part in re.split(r'[^A-Za-z0-9]+', hint)
                if part
            )
            candidate = f'{clean_hint}{base}'
            if candidate not in self.used_names:
                self.used_names.add(candidate)
                return candidate
        index = 2
        while f'{base}{index}' in self.used_names:
            index += 1
        candidate = f'{base}{index}'
        self.used_names.add(candidate)
        return candidate

    def register(
        self, config_cls: type[Config], hint: str | None = None
    ) -> _ClassSpec:
        existing = self.class_specs.get(config_cls)
        if existing is not None:
            return existing
        spec = _ClassSpec(
            config_cls=config_cls,
            generated_name=self._unique_name(config_cls, hint=hint),
        )
        self.class_specs[config_cls] = spec

        from kwconf.subconfig import SubConfig

        for key, template in config_cls.__default__.items():
            if isinstance(template, SubConfig):
                default = template.value
                child_cls = default if inspect.isclass(default) else type(default)
                if not issubclass(child_cls, Config):
                    raise TypeError(
                        f'SubConfig field {key!r} does not reference a Config: '
                        f'{child_cls!r}'
                    )
                child_cls = cast(type[Config], child_cls)
                child_spec = self.register(child_cls, hint=key)
                spec.field_name_map[key] = child_spec.generated_name
        self.class_order.append(config_cls)
        return spec

    def _render_subconfig_field(
        self, key: str, template: Any, spec: _ClassSpec
    ) -> list[str]:
        child_name = spec.field_name_map[key]
        field_kwargs = [f'default_factory={child_name}']
        if template.help:
            field_kwargs.append(f'description={template.help!r}')

        notes = []
        if template.choices is not None:
            notes.append(
                'SubConfig choices/selectors were not translated'
            )
        if template.allow_import is not None:
            notes.append(
                'SubConfig allow_import policy was not translated: '
                f'allow_import={template.allow_import!r}'
            )
        if not inspect.isclass(template.value):
            notes.append(
                'instance-backed SubConfig uses child class defaults; '
                'instance-specific overrides were not translated'
            )

        lines = []
        for note in notes:
            lines.extend(_review_lines(note))
        lines.extend(
            _field_lines(
                key,
                child_name,
                field_kwargs=field_kwargs,
            )
        )
        return lines

    def _render_value_field(self, key: str, template: Value) -> list[str]:
        annotation_expr, inference_note = _infer_annotation(template, self.state)
        notes = _field_review_notes(key, template)
        if inference_note is not None:
            notes.insert(0, inference_note)

        field_kwargs = []
        aliases = _normalize_aliases(template.alias)
        if aliases:
            self.state.pydantic_names.add('AliasChoices')
            alias_args = ', '.join(repr(v) for v in [key, *aliases])
            field_kwargs.append(f'validation_alias=AliasChoices({alias_args})')

        if template.help:
            field_kwargs.append(f'description={template.help!r}')

        if template.tags is not None and _json_compatible(template.tags):
            tag_expr = _render_value(template.tags, self.state)
            field_kwargs.append(
                "json_schema_extra={'kwconf_tags': " + tag_expr + '}'
            )

        if template.required:
            if template.default_factory is not None:
                notes.append(
                    'kwconf required=True and default_factory were both set; '
                    'the generated Pydantic field is required'
                )
            field_lines = _field_lines(
                key,
                annotation_expr,
                field_kwargs=field_kwargs,
                required=True,
            )
        elif template.default_factory is not None:
            try:
                factory_expr = _render_factory(
                    template.default_factory, self.state
                )
            except _RenderError as ex:
                raise ValueError(f'Cannot port field {key!r}: {ex}') from ex
            field_kwargs.insert(0, f'default_factory={factory_expr}')
            field_lines = _field_lines(
                key,
                annotation_expr,
                field_kwargs=field_kwargs,
            )
        else:
            try:
                default_expr = _render_value(template.value, self.state)
            except _RenderError as ex:
                raise ValueError(f'Cannot port field {key!r}: {ex}') from ex
            field_lines = _field_lines(
                key,
                annotation_expr,
                field_kwargs=field_kwargs,
                default_expr=default_expr,
            )

        lines = []
        for note in notes:
            lines.extend(_review_lines(note))
        lines.extend(field_lines)
        return lines

    def _class_review_notes(self, config_cls: type[Config]) -> list[str]:
        notes = []
        if getattr(config_cls, '__special_options__', False):
            notes.append(
                'kwconf --config/--dump/--dumps behavior was not translated'
            )
        if '__prog__' in config_cls.__dict__:
            prog = config_cls.__dict__['__prog__']
            notes.append(f'CLI prog={prog!r} was not translated')
        if '__epilog__' in config_cls.__dict__:
            notes.append('CLI epilog was not translated')
        if '__allow_abbrev__' in config_cls.__dict__:
            notes.append('argparse allow_abbrev policy was not translated')
        if '__fuzzy_hyphens__' in config_cls.__dict__:
            notes.append('kwconf fuzzy-hyphen CLI policy was not translated')
        if '__short_alias_clusters__' in config_cls.__dict__:
            notes.append(
                'kwconf short-alias cluster CLI policy was not translated'
            )
        if config_cls.__dict__.get('__validate__', 'warn') != 'warn':
            notes.append(
                'class-level kwconf validation policy was not translated'
            )
        return notes

    def _render_class(self, spec: _ClassSpec) -> str:
        from kwconf.subconfig import SubConfig

        config_cls = spec.config_cls
        lines = [f'class {spec.generated_name}(BaseModel):']
        doc = config_cls.__dict__.get('__description__')
        if not doc:
            doc = config_cls.__dict__.get('__doc__')
        if doc:
            doc = inspect.cleandoc(doc).replace('"""', '\\"\\"\\"')
            lines.extend(
                [
                    '    """',
                    *[f'    {line}' for line in doc.splitlines()],
                    '    """',
                ]
            )

        for note in self._class_review_notes(config_cls):
            lines.extend(_review_lines(note))

        if not config_cls.__default__:
            lines.append('    pass')
            return '\n'.join(lines)

        if len(lines) > 1:
            lines.append('')
        for index, (key, template) in enumerate(config_cls.__default__.items()):
            if not isinstance(template, Value):
                template = Value(template)
            if isinstance(template, SubConfig):
                field_lines = self._render_subconfig_field(key, template, spec)
            else:
                field_lines = self._render_value_field(key, template)
            if index:
                lines.append('')
            lines.extend(field_lines)
        return '\n'.join(lines)

    def port(self, root_cls: type[Config]) -> str:
        self.register(root_cls)
        class_blocks = [
            self._render_class(self.class_specs[cls])
            for cls in self.class_order
        ]
        pydantic_names = ', '.join(sorted(self.state.pydantic_names))
        imports = [
            'from __future__ import annotations',
            '',
        ]
        module_names = {'typing'} | self.state.modules
        for module_name in sorted(module_names):
            if module_name != 'builtins':
                imports.append(f'import {module_name}')
        imports.extend(['', f'from pydantic import {pydantic_names}', ''])
        header = [
            '# Generated by kwconf.Config.port_to_pydantic().',
            '# Target: Pydantic 2.',
            '# REVIEW(kwconf-port) comments identify untranslated CLI/source metadata.',
            '',
        ]
        return (
            '\n'.join(header + imports)
            + '\n\n'
            + '\n\n\n'.join(class_blocks)
            + '\n'
        )


def port_to_pydantic_source(config: Config) -> str:
    """Generate Pydantic 2 ``BaseModel`` source for a ``Config`` instance."""
    return _PydanticSourcePorter().port(type(config))
