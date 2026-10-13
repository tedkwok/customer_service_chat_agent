from langchain.tools import tool
from datetime import datetime
from langchain_core.runnables import RunnableConfig
import pandas as pd
from langchain_experimental.tools import PythonAstREPLTool


@tool("get_current_timestamp")
def get_current_timestamp():
    """Get the current server date-time in %Y-%m-%d %H:%M:%S format.

       Call this FIRST whenever a date range (e.g. for get_customer_history)
       is needed, so relative expressions like "last month" resolve correctly.
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@tool("analyze_pandas_dataset")
def analyze_pandas_dataset(dataset_dir: str, python_code: str) -> str:
    """Load a specific pandas dataset by name and executes Python analysis code on it.

    Args:
      dataset_dir: Directory of the dataset to analyze (directory of the dataset should be given when call the tools get_customer_history,get_production_info)
      python_code: Python code to run. Use Variable `df` to reference the target dataset.

    """
    try:

        target_df = pd.read_csv(dataset_dir)

    except Exception as e:

        print(f"[Agent]------- Error in reading the csv:{str(dataset_dir)}")
        return f"Error in reading the csv:{str(dataset_dir)} with exception: {str(e)}"

    tool_instance = PythonAstREPLTool(locals={"df":target_df, "pd": pd})

    return tool_instance.run(python_code)
