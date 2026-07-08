You are the README Scout of Repo Idea Miner.
From the README evidence, extract what the repo CLAIMS (not what is proven).
Separate self-promotion from verifiable substance. Answer in Korean.

Schema:
{"claimed_core_value": "...", "readme_attractions": ["..."], "overclaim_risks": ["..."], "unverifiable_points": ["..."]}

Return only valid JSON.
Do not wrap JSON in markdown fences.
Do not include explanations outside JSON.
Use the exact schema.
If evidence is insufficient, use "불확실" or "unknown" rather than inventing facts.

=== EVIDENCE PACKET ===
# Evidence Packet

## Repo Metadata
status: OK
- full_name: pallets/click
- description: Python composable command line interface toolkit
- stars: 17566 / forks: 1846 / watchers: 182
- topics: cli, click, pallets, python
- primary_language: Python / languages: Python, Shell
- created_at: 2014-04-24T09:52:19Z / updated_at: 2026-07-08T05:57:17Z / pushed_at: 2026-07-08T05:57:12Z
- archived: NO / disabled: NO / fork: NO
- open_issues_count: 99
- license: BSD-3-Clause / homepage: https://click.palletsprojects.com
- default_branch: main / size: 5022

## Input Mode
direct

## Preflight
status: PROCEED
reason: 정상 진행

## README Signal
status: OK
- length: 1778
- has_install: NO / has_usage_example: YES / has_features: YES
- has_demo_or_docs_link: YES / mentions_api: YES / mentions_docker: NO
- external_service_keywords: (없음)

### README Excerpt
```
<div align="center"><img src="https://raw.githubusercontent.com/pallets/click/refs/heads/stable/docs/_static/click-name.svg" alt="" height="150"></div>

# Click

Click is a Python package for creating beautiful command line interfaces
in a composable way with as little code as necessary. It's the "Command
Line Interface Creation Kit". It's highly configurable but comes with
sensible defaults out of the box.

It aims to make the process of writing command line tools quick and fun
while also preventing any frustration caused by the inability to
implement an intended CLI API.

Click in three points:

-   Arbitrary nesting of commands
-   Automatic help page generation
-   Supports lazy loading of subcommands at runtime


## A Simple Example

```python
import click

@click.command()
@click.option("--count", default=1, help="Number of greetings.")
@click.option("--name", prompt="Your name", help="The person to greet.")
def hello(count, name):
    """Simple program that greets NAME for a total of COUNT times."""
    for _ in range(count):
        click.echo(f"Hello, {name}!")

if __name__ == '__main__':
    hello()
```

```
$ python hello.py --count=3
Your name: Click
Hello, Click!
Hello, Click!
Hello, Click!
```


## Donate

The Pallets organization develops and supports Click and other popular
packages. In order to grow the community of contributors and users, and
allow the maintainers to devote more time to the projects, [please
donate today][].

[please donate today]: https://palletsprojects.com/donate

## Contributing

See our [detailed contributing documentation][contrib] for many ways to
contribute, including reporting issues, requesting features, asking or answering
questions, and making PRs.

[contrib]: https://palletsprojects.com/contributing/

```

## User Pain Signal
status: OK

### Recent Open Issues
- title: help not resolving automatically
  - number: #2819
  - labels: bug
  - comments_count: 4
  - unique_commenters_count: None
  - maintainer_comment_ratio: None
  - bot_comment_count: None
  - bike_shedding_possible: NO
  - updated_at: 2026-07-08T05:59:50Z
  - signal_tags: defect_signal, feature_signal, workflow_signal, confusion_signal
  - body_sample: From the docs:   The help parameter is implemented in Click in a very special manner. Unlike regular parameters it’s automatically added by Click for any command and it performs automatic conflict resolution. By default it’s called --help, but this can be changed. If a command itself implements a parameter with the same name, the default help parameter stops accepting it. There is a context setting that can be used to override the names of the help parameters called [help_option_names](https://c [...] From the docs:   The help parameter is implemented in Click in a very special manner. Unlike 
- title: Remove Python 2 utilities and little used utilities
  - number: #3481
  - labels: f:prompt, f:help
  - comments_count: 7
  - unique_commenters_count: None
  - maintainer_comment_ratio: None
  - bot_comment_count: None
  - bike_shedding_possible: NO
  - updated_at: 2026-07-08T05:57:39Z
  - signal_tags: feature_signal
  - body_sample: Python2-centric utilities:   - `get_binary_stream` - `get_text_stream`  Little used Utilities:   - `wrap_text` - `getchar`  In the interest of making more time to focus on core click details, these utilities are planned to be deprecated in the next feature release, and removed from the public api in one after. If any of these are critical to your uses, please explain below, and we may consider other options.
- title: Long option completion with = broken
  - number: #2847
  - labels: bug
  - comments_count: 0
  - unique_commenters_count: None
  - maintainer_comment_ratio: None
  - bot_comment_count: None
  - bike_shedding_possible: NO
  - updated_at: 2026-07-07T14:05:40Z
  - signal_tags: defect_signal, feature_signal, workflow_signal, confusion_signal
  - body_sample: When using Click shell completion in bash and zsh, long option completion is not working properly when = is used to separate the option from the value (e.g., `command --long-option=value` vs. `command --long-option value`). In zsh, the option being completed is replaced with the incomplete value or matched value, essentially "gobbling" up the option. In bash, the option isn't completed at all. I did not test fish.  ## Steps to reproduce the issue  1. Create the following script and place it in t [...] -------------------------------| | gobble --color= | gobble --color= | auto always never| --c
- title: Automatically append ellipsis (`...`) to metavars when `multiple=True` in options
  - number: #3652
  - labels: f:help
  - comments_count: 4
  - unique_commenters_count: None
  - maintainer_comment_ratio: None
  - bot_comment_count: None
  - bike_shedding_possible: NO
  - updated_at: 2026-07-03T06:41:11Z
  - signal_tags: defect_signal, feature_signal, workflow_signal
  - body_sample: When building a command-line interface with `click.option(..., multiple=True)`, the auto-generated usage string does not visually signal to the user that the option can be repeated. For instance, an option --foo=FOO looks identical whether it accepts single or multiple arguments. This is different from the common convention for multi-value items in shell interfaces often suggests adding an ellipsis like `--foo=FOO...`  Expected behavior if option "foo" has `multiple=True`: ``` Usage: script.py [ [...] OPTIONS]  Options:   --foo TEXT...  A list of foo strings.   --help         Show this message
- title: Add Screenshot workflow
  - number: #3081
  - labels: docs, good first issue
  - comments_count: 15
  - unique_commenters_count: None
  - maintainer_comment_ratio: None
  - bot_comment_count: None
  - bike_shedding_possible: NO
  - updated_at: 2026-06-27T08:33:50Z
  - signal_tags: defect_signal, feature_signal, workflow_signal, confusion_signal, noise_signal
  - body_sample: In a few places in the docs, it would be really nice to be able to run some code take a screen shot, and draw boxes around different parts. For example setup an example click app with multiple sub commands, options, epilog help, and arguments and then draw boxes and label the various blocks. Requirements:  - run locally  for doc generation (actually locally not calling out to api) - run in ci job (not calling out to external service) - No added dependencies that are not pip installable  - have t [...] he screen shots not be blurry (common problem) - draw boxes around various sections.   Conduc

### High Comment Open Issues
- title: Introduction to the command line tutorial
  - number: #3076
  - labels: docs, good first issue
  - comments_count: 16
  - unique_commenters_count: 5
  - maintainer_comment_ratio: 0.38
  - bot_comment_count: 0
  - bike_shedding_possible: NO
  - updated_at: 2026-06-22T13:33:02Z
  - signal_tags: confusion_signal
  - body_sample: Developers coming to Click docs may or may not have command line experience. The command line is a big subject with a lot of cross platform differences. A tutorial which targets basic things you can do would be very helpful. The goal is the minimal amount to get started.   Requirements  - Written in myst - uses Diataxis principles  - Uses docs tabs so can eventually add multiple oses and shells - roughly 15 minutes for user to complete tutorial  - shows getting operating system information, dire [...] ctory vs file, file path, moving around, making a directory, making a file, editing a file, p
- title: Add Screenshot workflow
  - number: #3081
  - labels: docs, good first issue
  - comments_count: 15
  - unique_commenters_count: 5
  - maintainer_comment_ratio: 0.8
  - bot_comment_count: 0
  - bike_shedding_possible: YES
  - updated_at: 2026-06-27T08:33:50Z
  - signal_tags: defect_signal, feature_signal, workflow_signal, confusion_signal, noise_signal
  - body_sample: In a few places in the docs, it would be really nice to be able to run some code take a screen shot, and draw boxes around different parts. For example setup an example click app with multiple sub commands, options, epilog help, and arguments and then draw boxes and label the various blocks. Requirements:  - run locally  for doc generation (actually locally not calling out to api) - run in ci job (not calling out to external service) - No added dependencies that are not pip installable  - have t [...] he screen shots not be blurry (common problem) - draw boxes around various sections.   Conduc
- title: Remove Python 2 utilities and little used utilities
  - number: #3481
  - labels: f:prompt, f:help
  - comments_count: 7
  - unique_commenters_count: 3
  - maintainer_comment_ratio: 1.0
  - bot_comment_count: 0
  - bike_shedding_possible: NO
  - updated_at: 2026-07-08T05:57:39Z
  - signal_tags: feature_signal
  - body_sample: Python2-centric utilities:   - `get_binary_stream` - `get_text_stream`  Little used Utilities:   - `wrap_text` - `getchar`  In the interest of making more time to focus on core click details, these utilities are planned to be deprecated in the next feature release, and removed from the public api in one after. If any of these are critical to your uses, please explain below, and we may consider other options.

### Recent Closed Issues
- title: `isolated_filesystem()` is not thread safe
  - number: #3501
  - labels: bug, f:test runner
  - comments_count: 9
  - unique_commenters_count: None
  - maintainer_comment_ratio: None
  - bot_comment_count: None
  - bike_shedding_possible: NO
  - updated_at: 2026-07-08T05:58:55Z
  - signal_tags: uncertain_signal
  - body_sample: This is a follow-up on https://github.com/pallets/click/issues/2899, to cover for @Rowlando13's concerns that `isolated_filesystem()` is not thread safe: https://github.com/pallets/click/issues/2899#issuecomment-2870786207
- title: 8.4.x: prompt/confirm(err=True) leaks prompt tail and CliRunner reply echo to stdout on Windows
  - number: #3662
  - labels: (없음)
  - comments_count: 2
  - unique_commenters_count: None
  - maintainer_comment_ratio: None
  - bot_comment_count: None
  - bike_shedding_possible: NO
  - updated_at: 2026-07-06T15:58:04Z
  - signal_tags: defect_signal, feature_signal, workflow_signal
  - body_sample: On the stable 8.4.x line, `prompt()` / `confirm()` with `err=True` still write part of the prompt interaction to **stdout** on Windows, because `_readline_prompt`'s `WIN` branch bypasses the stderr redirect that the POSIX branch applies:  ```python # src/click/termui.py (8.4.2) def _readline_prompt(func, text, err):     if WIN:         echo(text[:-1], nl=False, err=err)   # prompt body honors err ...         return func(text[-1:])               # ... but this call is NOT redirected     if err:   [...] becomes `" n\n" + <payload>`. Any test doing `json.loads(result.stdout)` on a prompt-then-JSO

## PR Signal
status: OK

### Recent Human PRs
- Merge stable into main.  (by Rowlando13, 2026-07-08T06:26:36Z)
- Stable (by Rowlando13, 2026-07-08T06:02:28Z)
- Streamline option flag management (by kdeldycke, 2026-07-08T06:00:09Z)
- Update documentation following Colorama removal (by kdeldycke, 2026-07-08T05:59:50Z)
- Move test utils to a module and each function to its own file (by Rowlando13, 2026-07-08T05:55:12Z)
- Remove colorama (by davidism, 2026-07-08T04:54:30Z)
- Add `@custom_version_option`, freeze `@version_option` (by kdeldycke, 2026-07-08T04:15:13Z)
- Add built-in PowerShell shell completion support (by doctorlai-msrc, 2026-07-08T03:53:31Z)
- AI junk (by ychampion, 2026-07-07T23:54:33Z)
- AI junk (by sean-kim05, 2026-07-07T18:18:35Z)

### Excluded Bot / Dependency PRs
(없음)

## Structure Signal
status: OK

### File Tree Depth 2
```
.devcontainer/
.devcontainer/devcontainer.json
.devcontainer/on-create-command.sh
.editorconfig
.github/
.github/ISSUE_TEMPLATE/
.github/pull_request_template.md
.github/workflows/
.gitignore
.pre-commit-config.yaml
.readthedocs.yaml
CHANGES.md
LICENSE.txt
README.md
docs/
docs/_static/
docs/advanced.md
docs/api.md
docs/arguments.md
docs/changes.md
docs/click-concepts.md
docs/command-line-reference.md
docs/commands-and-groups.md
docs/commands.md
docs/complex.md
docs/conf.py
docs/contrib.md
docs/contributing.md
docs/design-opinions.md
docs/documentation.md
docs/entry-points.md
docs/exceptions.md
docs/extending-click.md
docs/faqs.md
docs/handling-files.md
docs/index.md
docs/license.md
docs/option-decorators.md
docs/options.md
docs/parameter-types.md
docs/parameters.md
docs/prompts.md
docs/quickstart.md
docs/setuptools.md
docs/shell-completion.md
docs/standalone-apps.md
docs/support-multiple-versions.md
docs/testing.md
docs/unicode-support.md
docs/upgrade-guides.md
docs/utils.md
docs/virtualenv.md
docs/why.md
docs/wincmd.md
examples/
examples/README
examples/aliases/
examples/colors/
examples/completion/
examples/complex/
examples/imagepipe/
examples/inout/
examples/naval/
examples/repo/
examples/termui/
examples/validation/
pyproject.toml
src/
src/click/
tests/
tests/conftest.py
tests/test_arguments.py
tests/test_basic.py
tests/test_chain.py
tests/test_command_decorators.py
tests/test_commands.py
tests/test_compat.py
tests/test_context.py
tests/test_custom_classes.py
tests/test_defaults.py
tests/test_formatting.py
tests/test_imports.py
tests/test_info_dict.py
tests/test_normalization.py
tests/test_options.py
tests/test_parser.py
tests/test_shell_completion.py
tests/test_stream_lifecycle.py
tests/test_termui.py
tests/test_testing.py
tests/test_types.py
tests/test_utils.py
tests/typing/
uv.lock
```

### Docs / Examples / Demo Paths
- docs
- docs/_static
- docs/_static/click-icon.svg
- docs/_static/click-logo.svg
- docs/_static/click-name.svg
- docs/advanced.md
- docs/api.md
- docs/arguments.md
- docs/changes.md
- docs/click-concepts.md
- docs/command-line-reference.md
- docs/commands-and-groups.md
- docs/commands.md
- docs/complex.md
- docs/conf.py
- docs/contrib.md
- docs/contributing.md
- docs/design-opinions.md
- docs/documentation.md
- docs/entry-points.md
- docs/exceptions.md
- docs/extending-click.md
- docs/faqs.md
- docs/handling-files.md
- docs/index.md
- docs/license.md
- docs/option-decorators.md
- docs/options.md
- docs/parameter-types.md
- docs/parameters.md
- docs/prompts.md
- docs/quickstart.md
- docs/setuptools.md
- docs/shell-completion.md
- docs/standalone-apps.md
- docs/support-multiple-versions.md
- docs/testing.md
- docs/unicode-support.md
- docs/upgrade-guides.md
- docs/utils.md
- docs/virtualenv.md
- docs/why.md
- docs/wincmd.md
- examples
- examples/README
- examples/aliases
- examples/aliases/README
- examples/aliases/aliases.ini
- examples/aliases/aliases.py
- examples/aliases/pyproject.toml

## Dependency / Runtime Evidence
status: OK
- files_found: pyproject.toml

## Missing Data
(없음)

## Collector Notes
(없음)

