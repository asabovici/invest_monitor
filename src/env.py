"""Load a project-local .env file into os.environ.

Importing this module has the side effect of finding the nearest .env
(walking up from the current working directory) and merging its keys into
the process environment. Values already set in the real environment win,
matching the standard python-dotenv default.
"""
from dotenv import load_dotenv

# find_dotenv() default walks up from the cwd; usecwd=True keeps it predictable
# under streamlit / pytest, which can change __file__ semantics.
load_dotenv(override=False)
