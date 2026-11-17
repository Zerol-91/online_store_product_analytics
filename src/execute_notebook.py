"""Execute the analytical notebook with the current project Python interpreter."""

import argparse
import json
import sys
import tempfile
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpecManager

from local_config import ROOT


def execute_notebook(source, output):
    source, output = source.resolve(), output.resolve()
    if source.suffix != '.ipynb' or output.suffix != '.ipynb' or output.is_relative_to(ROOT/'data/raw'):
        raise ValueError('Use notebook files and write outside data/raw/.')
    notebook = nbformat.read(source, as_version=4)
    with tempfile.TemporaryDirectory(prefix='shop-notebook-') as folder:
        kernels = Path(folder)/'kernels'
        spec = kernels/'shop-python'
        spec.mkdir(parents=True)
        (spec/'kernel.json').write_text(json.dumps({'argv': [sys.executable, '-m', 'ipykernel_launcher',
            '-f', '{connection_file}'], 'display_name': 'Project Python', 'language': 'python'}), encoding='utf-8')
        manager = KernelManager(kernel_name='shop-python',
            kernel_spec_manager=KernelSpecManager(kernel_dirs=[str(kernels)]),
            connection_file=str(Path(folder)/'connection.json'))
        client = NotebookClient(notebook, km=manager, timeout=180, allow_errors=False,
                                resources={'metadata': {'path': str(source.parent)}})
        try:
            client.execute()
        finally:
            if manager.has_kernel:
                manager.shutdown_kernel(now=True)
    for cell in notebook.cells:
        cell.metadata.pop('execution', None)
    nbformat.validate(notebook)
    output.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(notebook, output)
    return sum(cell.cell_type == 'code' for cell in notebook.cells)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--notebook', type=Path, default=ROOT/'notebooks/analysis.ipynb')
    parser.add_argument('--output', type=Path, default=ROOT/'notebooks/analysis.ipynb')
    args = parser.parse_args()
    try:
        cells = execute_notebook(args.notebook, args.output)
    except Exception as error:
        print(f'Notebook execution failed: {error}', file=sys.stderr)
        return 1
    print(f'Executed {cells} code cells: {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
