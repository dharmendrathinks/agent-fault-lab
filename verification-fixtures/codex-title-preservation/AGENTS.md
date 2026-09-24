# Controlled coding task

- Change only `task_titles.py` and `test_task_titles.py`.
- Do not add dependencies, use the network, delegate work, or commit changes.
- Preserve every character except one terminal newline sequence: remove `\r\n`
  when present, otherwise remove one terminal `\n`, otherwise return the input.
- Add a focused regression test for meaningful leading and trailing spaces.
- Run `python3 -m unittest -v` and
  `python3 -m py_compile task_titles.py test_task_titles.py`.
- Your final response must follow the supplied JSON schema. A claim is your report,
  not evidence; use `unknown` rather than guessing.
