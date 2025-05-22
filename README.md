# Specification and Development Plan for a Bulk GitHub Repository Management Tool

## 1. Application Goal

The application serves to automate repetitive file management tasks across multiple GitHub repositories. It allows authenticated users to:
1.  Search and display a list of their repositories or repositories of a given organization.
2.  Select a subset of these repositories.
3.  Define an action to be performed in all selected repositories:
    *   Find a file (by name or content).
    *   Edit file content.
    *   Replace an entire file.
    *   Add a new file.
    *   Remove an existing file.
4.  Automatically create a new branch and a Pull Request for each change.

## 2. Current Status (as described above)

*   Streamlit application with GitHub OAuth login (login/logout logic in `app.py`, OAuth component in `github_utils.py`).
*   Loading and filtering repositories (personal or organizational) using `PyGithub` (`fetch_repositories` in `github_utils.py`).
*   User interface in `app.py` divided into tabs for selecting repositories and defining/executing actions.
*   `github_utils.py` module for interacting with the GitHub API:
    *   Loading repositories.
    *   Getting file content and its SHA.
    *   Creating/using existing branches.
    *   Updating/creating files.
    *   Deleting files.
    *   Creating Pull Requests.
    *   Searching for files in a repository (helper function `find_target_files`).
*   Uses `python-dotenv` for configuration.
*   Event logging implemented.

## 3. Planned Enhancements

### 3.1. User Interface (`app.py`)

*   **Repository Selection (Implemented):**
    *   Checkboxes next to each repository in the list for multiple selections.
    *   "Select/Deselect All Displayed Repositories" checkbox.
    *   The state of selected repositories is maintained in `st.session_state.selected_repos`.
    *   Filtering repositories by name and option to enter organization name.
*   **Action Panel (Implemented as tabs in `app.py`):**
    *   User selects an action using Tabs:
        *   "Remove File"
        *   "Update File" (includes replacing content of an existing file or creating a new one if it doesn't exist)
        *   "Add New File" (for explicitly adding a new file)
        *   (The originally planned "Find File" action as a separate PR-generating action is not implemented this way; the `find_target_files` function serves more as support.)
        *   (The original "Replace Entire File" action is covered by "Update File" or "Add New File" with an upload, if a file uploader were implemented.)
    *   **Dynamic Form Elements Based on Selected Action (Implemented/Partially Implemented):**
        *   **For all actions (except "Find File" - which is not a main action):**
            *   Text field for the file path in the repository (e.g., `src/config/settings.py`). (Implemented)
        *   **Find File (`find_target_files` function in `github_utils.py` supports this internally):**
            *   Specification: Text field for the file name (can include wildcards, e.g., `*.txt`). (Supported by `find_target_files`)
            *   Specification: Text field for the search content (text/regex). (Supported by `find_target_files`)
            *   (UI for directly calling this function and displaying results is not a main part of the PR generation workflow)
        *   **Update File (Replace file content / Create if not exists):**
            *   Text field for the file path. (Implemented)
            *   Text area (`st.text_area`) for entering new file content. (Implemented)
            *   Implicitly: If the file at the given path does not exist and content is provided, the `github_utils.update_file` function should create it.
        *   **Add New File (Add new file):**
            *   Text field for the target path in the repository (including file name). (Implemented)
            *   Text area (`st.text_area`) for entering the content of the new file. (Implemented)
            *   (The originally planned `st.file_uploader` is apparently not yet implemented; content is entered via text_area.)
        *   **Remove File (Remove file):**
            *   Text field for the file path. (Implemented)
    *   **PR Configuration (Implemented within forms for individual actions):**
        *   Text field for the new branch name (pre-filled, e.g., `batch-update/action-timestamp`).
        *   Text field for the PR title.
        *   Text area for the PR description.
        *   Text field for the PR target branch (e.g., `main`, `develop`, loads the repository's default branch).
    *   "Execute Action and Create PRs" button (or similar) to start. (Implemented)
*   **Displaying Results (Implemented):**
    *   After executing an action, a progress log is displayed in `st.text_area`.
    *   For each repository, status (success/failure) and a link to the created PR (if any) are displayed. Results are stored in `st.session_state.repo_actions_results`.
*   **Definition of Dynamic Placeholders (New):**
    *   Within the "2. Define & Execute Action" tab, a section (e.g., `st.expander`) will be added for defining dynamic placeholders.
    *   The user can add one or more placeholders. For each placeholder, configure:
        *   **Placeholder Name:** E.g., `my_version` (will be used as `{{my_version}}`).
        *   **File Path in Repository:** Source file from which the value is extracted (e.g., `project/config.json`, `deploy/values.yaml`).
        *   **Extraction Method:** Dropdown to select method:
            *   "Regular Expression (Regex)": Extracts value using a specified regex.
            *   "JSON Path": Extracts value from a JSON file using a JSONPath expression.
            *   "YAML Path": Extracts value from a YAML file using a dot-separated path.
        *   **Regex Pattern (only for "Regex" method):** Text field for entering the regular expression (e.g., `version = "([^"]+)"`).
        *   **Regex Group Index (only for "Regex" method, optional):** Numeric input to specify the capturing group (default is 1).
        *   **JSONPath Expression (only for "JSON Path" method):** Text field for entering the JSONPath expression (e.g., `$.version` or `dependencies.react`).
        *   **YAML Path (only for "YAML Path" method):** Text area (`st.text_area`) for entering one or more dot-separated paths to the value in a YAML file (e.g., `server.port` or `logging.level.root`), each path on a new line. The system will try paths in the specified order and use the value from the first successfully found path.
    *   Option to add and remove placeholder definitions.
    *   Defined placeholders will be stored in `st.session_state`.
*   **Using Dynamic Placeholders (New):**
    *   In the text fields for action configuration (file path, new/updated file content, commit message, PR title, PR description), the user can use the syntax `{{placeholder_name}}` to insert the dynamically loaded value.

### 3.2. Logic (`github_utils.py`)

Implemented or modified functions using `PyGithub`:

*   `fetch_repositories(access_token: str, search_name_query: str | None = None, organization_name: str | None = None) -> tuple[list[Repository] | None, str | None]`: Loads repositories, filters by name and organization.
*   `get_file_content(g: github.Github, repo_full_name: str, file_path: str, branch: str | None = None) -> tuple[str | None, str | None, str | None, str | None]`: Gets file content, its SHA, the repository's default branch, and an error message. Returns `(content, sha, default_branch_name, error_message)`.
*   `create_branch(g: github.Github, repo_full_name: str, new_branch_name: str, source_branch_name: str) -> tuple[bool, str | None, github.Branch.Branch | None]`: Creates a new branch from the source branch. If the branch already exists, it uses it. Returns `(success_status, message, branch_object)`.
*   `update_file(repo: github.Repository.Repository, file_path: str, new_content_str: str, commit_message: str, branch_name: str, current_sha_from_app: str | None, logger: logging.Logger) -> tuple[github.ContentFile.ContentFile | None, str | None, bool]`: Updates an existing file or creates a new one if `current_sha_from_app` is `None`. Returns `(updated_content_file, error_message, was_created)`. (Note: The exact signature and return value may differ slightly from the original specification; this is an estimate based on `app.py` and a preview of `github_utils.py`.)
*   `delete_file(g: github.Github, repo_full_name: str, file_path: str, commit_message: str, branch_name: str, sha: str) -> tuple[bool, str | None]`: Deletes a file. Requires the file's SHA. Returns `(success, error_message)`.
*   `create_pull_request(g: github.Github, repo_full_name: str, head_branch: str, base_branch: str, title: str, body: str) -> tuple[str | None, str | None]`: Creates a PR and returns its URL and any error message. Returns `(pr_url, error_message)`.
*   `find_target_files(g: github.Github, repo_full_name: str, target_branch: str, target_path_input: str | None = None, filename_filter_input: str | None = None, content_query_input: str | None = None) -> tuple[list[github.ContentFile.ContentFile], str | None]`: Searches for files by path, name (with fnmatch pattern support), or content. Serves as a helper function, not directly for PR generation. Returns `(list_of_content_files, error_message)`.
*   (The originally planned `create_file` function is likely integrated into `update_file` or handled in `app.py` by calling `update_file` without SHA for new files.)

*   **New function for placeholder extraction:**
    *   `extract_placeholder_value(g: github.Github, repo_full_name: str, branch: str, file_path: str, extraction_method: str, extraction_config: dict, logger: logging.Logger) -> tuple[str | None, str | None]`:
        *   Loads the file `file_path` from `repo_full_name` and branch `branch`.
        *   Applies `extraction_method` ("regex", "json_path", "yaml_path") with `extraction_config`.
            *   For "regex": `{'pattern': '...', 'group_index': 1}`.
            *   For "json_path": `{'jsonpath_expression': '$.version'}`.
            *   For "yaml_path": `{'yaml_path': 'server.port'}`. (Example, can now be a list: `{'yaml_path': ['server.port', 'application.port']}`)
        *   Returns `(extracted_value, error_message)`. `extracted_value` is `None` if extraction failed or the path led to a `null` value. `error_message` contains a description of the error if one occurred, otherwise it is `None`.

### 3.3. Workflow in `app.py` when an action is triggered:

1.  Verify login and selected repositories. (Implemented)
2.  Load placeholder definitions from `st.session_state`.
3.  For each selected repository:
    a.  **Process Placeholders (New):**
        i.  For each defined placeholder, call `extract_placeholder_value` from `github_utils.py` to get its value for the current repository.
        ii. Store the loaded placeholder values (or their default values) for the current repository.
        iii. Create copies of action parameters (paths, content, commit messages, etc.).
        iv. Replace all occurrences of `{{placeholder_name}}` in these copies of action parameters with their loaded values. If an error occurs during placeholder value extraction for a given repository (the `extract_placeholder_value` function returns an error message), the action for this repository is skipped, and a prominent error message is logged. If extraction proceeds without error but the resulting value is `None` (e.g., a YAML/JSON path led to `null`), this value is interpreted as an empty string for replacement.
    b.  Get the repository's default branch name (used as default for PR target branch and as a base for the new working branch if not specified otherwise). `get_file_content` can help get the default branch. (Implemented)
    c.  Create a new working branch from the default or specified source branch (`create_branch`) – the branch name can also contain placeholders. (Implemented, extend for placeholders)
    d.  According to the chosen action (Remove, Update, Add) – action parameters (paths, content, etc.) are already with replaced placeholders:
        *   **Remove File:**
            i.  Get the file's SHA (`get_file_content`).
            ii. Perform the `delete_file` operation.
        *   **Update File:**
            i.  Get the file's SHA, if it exists (`get_file_content`).
            ii. Perform the `update_file` operation (with or without SHA, which determines if it's an update or create).
        *   **Add New File:**
            i.  Perform the `update_file` operation without SHA (or a specialized create function, if it exists).
    e.  If the file operation succeeded, create a PR (`create_pull_request`) – PR title and description can also contain placeholders. (Implemented, extend for placeholders)
    f.  Record the result (success/failure, PR URL) in `st.session_state.repo_actions_results`. (Implemented)
4.  Display summary results to the user. (Implemented)

## 4. Important Notes

*   **Error Handling:** Thoroughly handle errors from the GitHub API (rate limits, non-existent files/branches, conflicts, etc.). Return understandable error messages to the user.
*   **File SHAs:** To update and delete files via the GitHub API, their current SHA is usually required. This means the file must first be read before modification/deletion.
*   **Commit Message and PR Description:** Should be informative. Templates with variables (repository name, file name, action type) can be used.
*   **Large Number of Repositories:** Operations on a large number of repositories can take a long time. Streamlit might "freeze." Consider asynchronous processing or sequential processing with continuous UI updates if necessary (for now, we can start synchronously).
*   **Security:** The user manipulates their own repositories. Actions are performed under their token. No other sensitive data should be stored.
*   **`Github` Instance:** The `g = Github(access_token)` instance is created in `app.py` after login and is passed to relevant functions in `github_utils.py`. (Implemented)

## 5. Further Possible Improvements (Beyond Current Scope)

*   Support for "dry run" (preview changes without applying them).
*   More advanced file content operations (e.g., find and replace using regex).
*   Option to save and load action configurations.
*   Integration with CI/CD for automatic execution of these tasks.
*   Pagination / "load more" for the repository list if there are many. 