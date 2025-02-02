"""
This is just a script to convert gamma CLI help files into a ga_sar_workflow test
proxy object for testing/validation.

The expected input path is the "gamma_usage" directory generated from the
`gamma_usage_gen.bash` script in the utils directory.

And the generated file is put into a hard-coded output directory ~/GA/py_gamma_test_proxy.py

See generated file insar/tests/py_gamma_test_proxy.py for latest generated output.
"""

from collections import OrderedDict
from pathlib import Path
import regex
import argparse


def _usage2decl(module, program, file):
    """
    Parses a gamma program's CLI help output to create a python representation of the program
    and it's parameters, for use by the code generator in this script below.

    This isn't intended to be used by any other module.

    :param module:
        The name of the gamma module the program belongs to (eg: DISP)
    :param program:
        The name of the gamma program the file describes the usage of (eg: create_diff_par)
    :param file:
        The file object to read the program CLI help from, for parsing.

    :returns:
        A dict containing a declaration of the program specifically for the code generator below.
    """
    state = 0
    params = OrderedDict()

    lines = file.read().splitlines()

    # Ignore files that only have a single error line
    # - these are GAMMA programs which failed to load shared libraries
    # - because they use thidpartyies we don't build/support, which is fine
    # - as these programs are intentionally unsupported/unused by us / our wrapper.
    #
    # The correct "fix" to this, for users who need to use one of these programs, is to
    # add that thirdparty library to our supported/built libraries in the virtual environment we build
    # so that program can be loaded/run.
    if not lines or len(lines) <= 2:
        print(f"Skipping {module}/{program} due to invalid usage file (this is probably not an issue)")
        return None

    for line in lines:
        if line.strip().startswith("**") or len(line.strip()) == 0:
            continue

        if state == 0:
            if line.startswith("usage:"):
                # Grab arugments from 'usage' line:
                m = regex.match(
                    r"usage: +([\w\-\\/_]+)( *\<([\w\-\\/_]+)\>)*( *\[([\w\-\\/_]+)\])*", line
                )

                try:
                    required_args = m.captures(3)
                    optional_args = m.captures(5)
                    all_args = required_args + optional_args
                    state = 1

                except Exception as e:
                    print("line:", line)
                    print(m)
                    print(e)
                    exit()

        elif state == 1:
            if line.startswith("input parameters:"):
                state = 2
                last_arg = -1

        elif state == 2:
            desc = ""

            # Start parsing new arg
            if not line.startswith("    "):
                # Stop parsing once we've got all our args
                # - this basically ignores suffix doco after the param descriptions
                if last_arg == len(all_args):
                    break

                argname = line.split()[0]
                desc_argname = argname

                ignore_arg = argname.lower().startswith("note:")
                ignore_arg |= argname.lower().startswith("remark")
                ignore_arg |= argname.lower().startswith("example:")

                # HACK: This is... not ideal, "..." (usually?) means variable number of arguments
                ignore_arg |= argname.startswith("...")

                if not ignore_arg:
                    # Assert we're reading in the correct order
                    # assert(all_args.index(argname) == last_arg+1)
                    # DISABLED for now... their documentation has inconsistent namings...
                    last_arg += 1

                    # HACK: gamma's help is full of typos, we trust the initial argnames... not what's in the desc
                    try:
                        positional_argname = all_args[last_arg]
                        argname = positional_argname
                    except Exception:
                        # Ignore failures indexing all_args, we don't handle variable sized arguments which
                        # some programs have at the tail of the arguments.
                        # (eg: input0 ... inputN at the end of some programs)
                        pass

                    is_opt = last_arg >= len(required_args)

                    params[argname] = {
                        "desc": "",
                        "optional": is_opt,
                    }

                desc_starts = len(desc_argname) + 2
                desc = line[desc_starts:].lstrip()

                is_inoutfile = desc.startswith("(input/output)")
                is_infile = desc.startswith("(input)") or is_inoutfile
                is_outfile = desc.startswith("(output)") or is_inoutfile

                if not is_outfile:
                    # Special case for certain "(input)"'s that aren't actually files...
                    # eg: coord_to_sarpix has (input) args that are numbers in meters "(m)" or degrees "(deg.)"
                    # eg: par_RSAT2_SLC has (input) image polarization: HH, VV, HV, VH
                    not_file_patterns = [
                        " (m)",
                        " (deg",
                        "polarization",
                        "meters",
                        "days",
                        "float",
                        "mode"
                    ]

                    for pattern in not_file_patterns:
                        if pattern in desc:
                            is_inoutfile = False
                            is_infile = False
                            is_outfile = False

            else:  # continue parsing existing arg
                desc = line.lstrip()

            if ignore_arg:
                continue

            params[argname]["desc"] += desc + "\n"

            # parse description
            enum_prefix = regex.match(r" *(\d+):.*", desc)

            # detect filepath params
            if is_infile or is_outfile:
                params[argname]["type"] = "path"
                params[argname]["is_infile"] = is_infile
                params[argname]["is_outfile"] = is_outfile

            # detect enum params
            elif enum_prefix:
                params[argname]["type"] = "enum"

                if "enum" in params[argname]:
                    params[argname]["enum"].append(int(enum_prefix[1]))
                else:
                    params[argname]["enum"] = [int(enum_prefix[1])]

            # All other variables have no validation info
            else:
                params[argname]["type"] = "unknown"

    return {"module": module, "program": program, "params": params}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert gamma CLI help files into a ga_sar_workflow test proxy object for testing/validation generated at ~/GA/py_gamma_test_proxy.py"
    )
    parser.add_argument(
        "path",
        type=str,
        help="The base path to the gamma usage directory generated by gamma_usage_gen.bash",
    )

    args = parser.parse_args()
    basedir = Path(args.path)

    decls = {}

    # A set of programs our parser doesn't handle properly yet
    blacklist = [
        "coord_trans",  # This isn't a normal gamma command
        "mosaic",
        "JERS_fix",
        "comb_hsi",
        "soil_moisture",
        "validate",
        "ASAR_XCA",  # This has two programs of the same name?
    ]

    # A set of programs that have variable arguments
    vararg_programs = [
        "rascc_mask_thinning"
    ]

    # Parse program details
    for module_dir in basedir.iterdir():
        module = module_dir.name

        decls[module] = {}

        for usage_path in module_dir.iterdir():
            program = usage_path.stem

            # Ignore some unused problematic programs
            if program in blacklist:
                continue

            with usage_path.open("r") as usage_file:
                decl = _usage2decl(module, program, usage_file)

            if not decl:
                continue

            decls[module][program] = decl

    # Generate python stubs
    outdir = Path.home() / "GA" / "py_gamma_test_proxy.py"

    with outdir.open("w") as file:

        def writelines(indent, lines):
            for line in lines:
                if len(line.strip()) > 0:
                    file.write("    " * indent)
                    file.write(line)

                file.write("\n")

        writelines(
            0,
            [
                "from pathlib import Path",
                "from typing import Sequence, NamedTuple, Dict, Optional",
                "from collections import Counter",
                "import inspect",
                "",
                "# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!",
                "# WARNING: This file is automatically generated!",
                "# See utils/gamma_usage2py.py",
                "# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!",
                "",
                'GammaCall = NamedTuple("GammaCall", [("module", str), ("program", str), ("parameters", Dict[str, object]), ("status", int)])',
                "",
                "",
                "class SimpleParFile(object):",
                "    values = {}",
                "",
                "    def __init__(self, path):",
                "        with open(path, 'r') as file:",
                "            lines = file.read().splitlines()[1:]  # Skip header lines",
                "",
                "            for line in lines:",
                "                value_id = line.split(':')[0]",
                "                if len(value_id.strip()) == 0:",
                "                    continue",
                "",
                "                value_data = line[len(value_id)+2:].strip()",
                "",
                "                self.values[value_id] = value_data",
                "",
                "    def get_value(self, value_id: str, dtype=str, index: Optional[int] = None):",
                "        def attempt_convert(val):",
                "            try:",
                "                return dtype(val)",
                "            except:",
                "                return val",
                "",
                "        if index is not None:",
                "            return attempt_convert(self.values[value_id].split()[index])",
                "        else:",
                "            return [attempt_convert(i) for i in self.values[value_id].split()]",
                "",
                "",
                "class GammaProxy(object):",
            ],
        )

        writelines(
            1,
            [
                "ParFile = SimpleParFile",
                "",
                "validate_inputs: bool = True",
                "mock_outputs: bool = False",
                "",
                "call_sequence: Sequence[GammaCall]",
                "call_count: Counter",
                "error_count: int",
                "",
                "_exception_type: type",
                "_wraps: object",
                "_fail_reason: str",
                "",
                "def __init__(self, exception_type=None, wraps=None):",
                "    self.reset_proxy()",
                "    self._exception_type = exception_type",
                "    self._wraps = wraps",
                "",
                "def reset_proxy(self):",
                "    self.call_sequence = []",
                "    self.call_count = Counter()",
                "    self.error_count = 0",
                "    self._fail_reason = None",
                "",
                "def _validate(self, cmd, is_valid, fail_reason):",
                "    if not is_valid:",
                "        stat = -1",
                "        self._fail_reason = fail_reason",
                '        raise ValueError(f"Invaid pg.{cmd} parameters ({self._fail_reason})")',
                "",
                "def _on_error(self, cmd, params, status):",
                "    if status is None or status == 0:",
                "        return",
                "",
                "    if self._exception_type is None:",
                "        return",
                "",
                '    raise self._exception_type(f"failed to execute pg.{cmd} ({self._fail_reason})")',
                "",
                "def _gamma_call(self, gamma_module: str, gamma_program: str, program_args):",
                "    result = (0, \"\", \"\")",
                "",
                "    if self._wraps is not None:",
                "        result = getattr(self._wraps, gamma_program)(*program_args)",
                "",
                "    self.call_count[gamma_program] += 1",
                "    self.call_sequence.append(GammaCall(gamma_module, gamma_program, program_args, result[0]))",
                "    self._on_error(gamma_program, program_args, result[0])",
                "",
                "    return result",
                "",
                "def _clean_call_args(self, values, sig: inspect.Signature):",
                "    # Subset argnames to just those the user provided",
                "    # (eg: ignore the default-value params they didn't provide)",
                "    del values[\"self\"]",
                "    argnames = list(sig.parameters.keys())[:len(values)]",
                "",
                "    # And then also remove the trailing default args w/ no value",
                "    for name in reversed(argnames.copy()):",
                "        param = sig.parameters[name]",
                "",
                "        # Stop once we hit non-default values",
                "        if param.default == inspect.Parameter.empty:",
                "            break",
                "",
                "        # And also stop once we hit values the call is being passed",
                "        val = values[argnames[-1]]",
                "        if val and val != \"-\":",
                "            break",
                "",
                "        argnames.pop()",
                "",
                "    return [values[i] for i in argnames]",
            ],
        )

        def clean_arg_name(name):
            return name.replace("-", "_").replace("/", "_").replace("\\", "_")

        for module, programs in decls.items():
            for program, decl in programs.items():

                args = ""
                has_optionals = False

                for argname, param in decl["params"].items():
                    if args != "":
                        args += ", "

                    argname = clean_arg_name(argname)
                    argname = "definition" if argname == "def" else argname

                    args += argname

                    if param["type"] == "path":
                        args += ": str"

                    if param["optional"] or has_optionals:
                        args += " = None"
                        has_optionals = True

                var_args = ", *args" if program in vararg_programs else ""

                program_funcname = program.replace("-", "_")

                #
                # Generate argument validation function
                #

                writelines(
                    1,
                    [
                        "",
                        f'def _validate_{program_funcname}(self, {args}{var_args}):',
                    ],
                )

                num_validated_args = 0

                for argname, param in decl["params"].items():
                    argname = clean_arg_name(argname)
                    argname = "definition" if argname == "def" else argname

                    # TODO: assert required args are not None, and allow optionals to be none

                    if param["type"] == "path":
                        # Check input files exist
                        if param["is_infile"] and not param["is_outfile"]:
                            writelines(
                                2,
                                [
                                    f"if {argname} is not None:",
                                    f'    self._validate("{program}", {argname} == "-" or Path({argname}).exists(), f"{argname} path does not exist ({{{argname}}})")',
                                ],
                            )

                            num_validated_args += 1

                    elif param["type"] == "enum":
                        valid_values = param["enum"]

                        writelines(
                            2,
                            [
                                f"valid_values = {repr(valid_values)}"
                                + (" + [None]" if param["optional"] else ""),
                                f'self._validate("{program}", {argname} == "-" or {argname} in valid_values, f"{argname} is not a valid value (expects: {{valid_values}}, got: {{{argname}}})")',
                            ],
                        )

                        num_validated_args += 1

                if num_validated_args == 0:
                    writelines(2, ["pass"])

                #
                # Generate output file mocking for unit tests
                #

                writelines(
                    1,
                    [
                        "",
                        f'def _mock_{program_funcname}_outputs(self, {args}{var_args}):',
                    ],
                )

                num_mocked_outputs = 0

                for argname, param in decl["params"].items():
                    argname = clean_arg_name(argname)
                    argname = "definition" if argname == "def" else argname

                    # TODO: assert required args are not None, and allow optionals to be none

                    if param["type"] == "path":
                        # Touch in/out files if they don't already exist
                        if param["is_outfile"] and param["is_infile"]:
                            writelines(
                                2,
                                [
                                    f'if {argname} is not None and {argname} != "-" and not Path({argname}).exists():',
                                    f"    Path({argname}).touch()",
                                ],
                            )

                            num_mocked_outputs += 1

                        # Touch output files
                        elif param["is_outfile"]:
                            writelines(
                                2,
                                [
                                    f'if {argname} is not None and {argname} != "-":',
                                    f"    Path({argname}).touch()",
                                ],
                            )

                            num_mocked_outputs += 1

                if num_mocked_outputs == 0:
                    writelines(2, ["pass"])

                #
                # Generate actual function call wrapper
                #

                writelines(
                    1,
                    [
                        "",
                        f'def {program_funcname}(self, {args}{var_args}):',
                        f"    supplied_args = self._clean_call_args(locals(), inspect.signature(self.{program_funcname}))",
                        "",
                        "    if self.validate_inputs:",
                        f"        self._validate_{program_funcname}(*supplied_args)",
                        "",
                        "    if self.mock_outputs:",
                        f"        self._mock_{program_funcname}_outputs(*supplied_args)",
                        "",
                        f'    return self._gamma_call("{module}", "{program}", supplied_args)',
                        "",
                    ],
                )
