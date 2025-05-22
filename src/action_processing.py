import re
import logging # For type hinting Logger
import datetime # For timestamp generation
from typing import Dict, List, Tuple, Optional, Any
# import github_utils # To call GitHub utility functions
from . import github_utils # To call GitHub utility functions
from .github_utils import PlaceholderExtractionResult, Repository, FileContentResult # Specific imports for type hinting if needed
from github import Github # For type hinting and creating Github instance
import github # <-- ADDED IMPORT FOR THE ENTIRE MODULE

# Helper function to process placeholders in a string
def process_placeholders_in_string(text_to_process: str, resolved_placeholders: dict, logger: logging.Logger) -> str:
    if not isinstance(text_to_process, str): # Ensure we are working with a string
        return text_to_process

    def replace_match(match):
        placeholder_name = match.group(1)
        return resolved_placeholders.get(placeholder_name, match.group(0)) # Return original if not found

    try:
        # Regex to find {{placeholder_name}} or {{ placeholder_name }}
        processed_text = re.sub(r"\{\{\s*([^}\s]+)\s*\}\}", replace_match, text_to_process)
    except Exception as e:
        logger.error(f"Error during placeholder substitution: {e}. Original text: '{text_to_process}'", exc_info=True)
        return text_to_process # Return original text on error
    return processed_text

# --- NEW HELPER FUNCTIONS ---

def _resolve_all_placeholders_for_repo(
    g: Github, 
    repo_info: Repository, 
    defined_placeholders: list, 
    timestamp_str: str, 
    logger: logging.Logger
) -> tuple[dict, list[str], bool]:
    """
    Resolves built-in and user-defined placeholders for a single repository.
    Returns a dictionary of resolved placeholders, an action log list, and a success flag.
    """
    action_log = []
    resolved_placeholders = {
        'repo_name': repo_info.name,
        'repo_full_name': repo_info.full_name,
        'repo_default_branch': repo_info.default_branch,
        'timestamp': timestamp_str
    }
    all_placeholders_successfully_resolved = True

    for ph_def in defined_placeholders:
        ph_name = ph_def.get("name")
        ph_file_path = ph_def.get("file_path")
        ph_method = ph_def.get("method")
        ph_config = ph_def.get("config", {})

        if not ph_name or not ph_file_path or not ph_method:
            msg = f"- WARNING: Invalid placeholder definition skipped: Name='{ph_name}', Path='{ph_file_path}', Method='{ph_method}'"
            logger.warning(f"[{repo_info.full_name}] {msg}")
            action_log.append(msg)
            continue

        try:
            placeholder_extraction_result = github_utils.extract_placeholder_value(
                g, repo_info.full_name, repo_info.default_branch,
                ph_file_path, ph_method, ph_config, logger
            )
            if placeholder_extraction_result.error:
                err_msg = f"Could not resolve placeholder '{{{{{ph_name}}}}}' from '{ph_file_path}': {placeholder_extraction_result.error}. This repository will be skipped."
                logger.error(f"[{repo_info.full_name}] {err_msg}")
                action_log.append(f"- ERROR: {err_msg}")
                all_placeholders_successfully_resolved = False
                break 
            resolved_placeholders[ph_name] = str(placeholder_extraction_result.value) if placeholder_extraction_result.value is not None else ""
            action_log.append(f"- INFO: Placeholder '{{{{{ph_name}}}}}' (from '{ph_file_path}') resolved to: '{resolved_placeholders[ph_name]}'")
        except Exception as e:
            err_msg = f"Exception while resolving placeholder '{{{{{ph_name}}}}}' from '{ph_file_path}': {e}. This repository will be skipped."
            logger.error(f"[{repo_info.full_name}] {err_msg}", exc_info=True)
            action_log.append(f"- ERROR: {err_msg}")
            all_placeholders_successfully_resolved = False
            break
            
    return resolved_placeholders, action_log, all_placeholders_successfully_resolved


def _process_action_params(
    action_params_from_form: dict, 
    resolved_placeholders: dict, 
    logger: logging.Logger,
    param_keys_for_phase2_reprocessing: list[str]
) -> tuple[dict, list[str]]:
    """
    Processes action parameters in two phases:
    1. Replaces all placeholders in all string parameters.
    2. Adds the processed file_path (or target_file_path) to resolved_placeholders as 'file_path'.
    3. Re-processes specific parameters (like commit messages, PR titles/bodies) that might use '{{file_path}}'.
    """
    processing_log = []
    processed_params = {k: v for k, v in action_params_from_form.items()} # Create a mutable copy

    # Phase 1: Process all parameters
    defined_ph_names_for_logging = {name for name in resolved_placeholders.keys() if name not in ['repo_name', 'repo_full_name', 'repo_default_branch', 'timestamp', 'file_path']}

    for key, value in processed_params.items():
        if isinstance(value, str):
            original_value = value
            processed_params[key] = process_placeholders_in_string(value, resolved_placeholders, logger)
            if original_value != processed_params[key]:
                processing_log.append(f"- INFO: Param (Phase 1) '{key}' ('{original_value}') processed to: '{processed_params[key]}'")
            # Log warning if a known placeholder pattern was in the original but value didn't change (could be a typo in placeholder name)
            elif any(f"{{{{{name}}}}}" in original_value for name in defined_ph_names_for_logging) and original_value == processed_params[key]:
                 processing_log.append(f"- WARNING: Param (Phase 1) '{key}' ('{original_value}') might contain an unresolved or mistyped user-defined placeholder.")


    # Get the processed file_path (key might be 'file_path' or 'target_file_path')
    # This is the path *after* initial placeholder resolution
    processed_file_path_for_messages = processed_params.get("file_path", processed_params.get("target_file_path", ""))
    
    # Update resolved_placeholders with the actual file_path being operated on
    # This allows {{file_path}} to be used in commit messages, PR titles etc.
    original_file_path_placeholder_value = resolved_placeholders.get("file_path")
    resolved_placeholders["file_path"] = processed_file_path_for_messages
    if original_file_path_placeholder_value != processed_file_path_for_messages : # Log if it changed or was added
        processing_log.append(f"- INFO: Built-in placeholder '{{{{file_path}}}}' (for messages) set to: '{processed_file_path_for_messages}'")

    # Phase 2: Re-process parameters that typically use {{file_path}} or other placeholders that depend on Phase 1
    for key in param_keys_for_phase2_reprocessing:
        if key in processed_params and isinstance(processed_params[key], str):
            original_value = processed_params[key] # Value after phase 1
            # Reprocess with the potentially updated resolved_placeholders (e.g. with 'file_path' now correctly set)
            processed_params[key] = process_placeholders_in_string(original_value, resolved_placeholders, logger)
            if original_value != processed_params[key]:
                processing_log.append(f"- INFO: Param (Phase 2) '{key}' ('{original_value}') re-processed to: '{processed_params[key]}'")

    return processed_params, processing_log

# --- MAIN FUNCTIONS FOR EXECUTING ACTIONS ---

def execute_remove_file_action(
    g: Github, 
    selected_repo_infos: list[Repository],
    defined_placeholders: list, 
    action_config_from_form: dict, # Contains rf_file_path, rf_branch_name, etc.
    logger: logging.Logger
) -> list[dict]:
    """
    Executes the 'Remove File' action for the selected repositories.
    action_config_from_form should map directly to form inputs e.g.
    {
        "file_path": form_values["rf_file_path"],
        "branch_name": form_values["rf_branch_name"],
        "commit_message": form_values["rf_commit_message"],
        "pr_title": form_values["rf_pr_title"],
        "pr_body": form_values["rf_pr_body"]
    }
    """
    batch_action_results = []
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    default_branch_name_template = action_config_from_form.get("rf_branch_name", f"remove-file-{timestamp_str}")


    for repo_info in selected_repo_infos:
        action_log_for_repo = [f"Action: Remove File on repo {repo_info.full_name} (default branch: {repo_info.default_branch})"]
        logger.info(f"Processing 'Remove File' for repo: {repo_info.full_name}")

        resolved_ph, ph_log, ph_ok = _resolve_all_placeholders_for_repo(g, repo_info, defined_placeholders, timestamp_str, logger)
        action_log_for_repo.extend(ph_log)
        if not ph_ok:
            batch_action_results.append({"repo": repo_info.name, "success": False, "message": "\n".join(action_log_for_repo)})
            continue

        # Ensure "file_path" from form (e.g. rf_file_path) is mapped to "file_path" for _process_action_params
        current_action_params_for_processing = {
            "file_path": action_config_from_form.get("rf_file_path"),
            "branch_name": default_branch_name_template, # Will be processed by _process_action_params
            "commit_message": action_config_from_form.get("rf_commit_message"),
            "pr_title": action_config_from_form.get("rf_pr_title"),
            "pr_body": action_config_from_form.get("rf_pr_body")
        }
        
        params_to_reprocess_phase2 = ["branch_name", "commit_message", "pr_title", "pr_body"]
        processed_params, params_log = _process_action_params(current_action_params_for_processing, resolved_ph, logger, params_to_reprocess_phase2)
        action_log_for_repo.extend(params_log)

        target_file_path = processed_params.get("file_path", "")
        if not target_file_path:
            action_log_for_repo.append(f"- ERROR: Processed file path is empty. Skipping repo.")
            batch_action_results.append({"repo": repo_info.name, "success": False, "message": "\n".join(action_log_for_repo)})
            continue
        
        # Resolve target branch name (this was `working_branch_name` before)
        target_branch_for_action = processed_params.get("branch_name") 
        if not target_branch_for_action or not target_branch_for_action.strip():
            target_branch_for_action = f"remove-file-fallback-{timestamp_str}"
            action_log_for_repo.append(f"- INFO: Target branch name was empty or invalid, defaulted to '{target_branch_for_action}'.")

        branch_to_operate_on = target_branch_for_action
        branch_created_this_run = False

        try:
            repo_api = g.get_repo(repo_info.full_name)
            logger.info(f"Checking if branch '{target_branch_for_action}' exists in repo '{repo_api.full_name}'.")
            repo_api.get_git_ref(f"heads/{target_branch_for_action}")
            action_log_for_repo.append(f"- INFO: Using existing branch '{target_branch_for_action}'.")
        except github.UnknownObjectException:
            action_log_for_repo.append(f"- INFO: Branch '{target_branch_for_action}' does not exist. Attempting to create it from '{repo_info.default_branch}'.")
            branch_op_result = github_utils.create_branch(g, repo_info.full_name, target_branch_for_action, repo_info.default_branch)
            action_log_for_repo.append(f"- INFO: Branch creation op: {branch_op_result.message}")
            if not branch_op_result.success:
                batch_action_results.append({"repo": repo_info.name, "success": False, "message": "\n".join(action_log_for_repo)})
                continue
            branch_created_this_run = True
        except Exception as e_check_branch:
            action_log_for_repo.append(f"- ERROR: Could not check/create branch '{target_branch_for_action}': {e_check_branch}")
            batch_action_results.append({"repo": repo_info.name, "success": False, "message": "\n".join(action_log_for_repo)})
            continue

        action_log_for_repo.append(f"- INFO: Attempting to get SHA for file '{target_file_path}' on branch '{branch_to_operate_on}'.")
        file_content_res = github_utils.get_file_content(g, repo_info.full_name, target_file_path, branch_to_operate_on)
        if file_content_res.error or not file_content_res.sha:
            err_msg = f"Could not get SHA for file '{target_file_path}': {file_content_res.error or 'SHA not found'}. File may not exist on branch '{branch_to_operate_on}' or path is a directory."
            action_log_for_repo.append(f"- ERROR: {err_msg}")
            batch_action_results.append({"repo": repo_info.name, "success": False, "message": "\n".join(action_log_for_repo)})
            continue
        action_log_for_repo.append(f"- INFO: SHA for '{target_file_path}' is '{file_content_res.sha}'. Proceeding with deletion.")

        delete_status = github_utils.delete_file(
            g, repo_info.full_name, target_file_path,
            processed_params["commit_message"], branch_to_operate_on, file_content_res.sha
        )
        action_log_for_repo.append(f"- INFO: File deletion result: {delete_status.message or ('Successfully deleted' if delete_status.success else 'Failed')}")
        if not delete_status.success:
            batch_action_results.append({"repo": repo_info.name, "success": False, "message": "\n".join(action_log_for_repo)})
            continue
        
        pr_result = github_utils.create_pull_request(
            g, repo_info.full_name, branch_to_operate_on, repo_info.default_branch,
            processed_params["pr_title"], processed_params["pr_body"]
        )
        action_log_for_repo.append(f"- INFO: PR creation: {pr_result.message}") # Message might be None on success
        if pr_result.html_url:
            batch_action_results.append({"repo": repo_info.name, "success": True, "message": "\n".join(action_log_for_repo), "pr_url": pr_result.html_url})
        else: # Successful action, but PR failed or already existed without giving a URL in this path
             final_message = "\n".join(action_log_for_repo)
             if pr_result.message: # Add PR message if it exists (e.g., error, or "already exists")
                 final_message += f"\n- PR Status: {pr_result.message}"
             else: # Should ideally not happen if URL is None, means an unexpected state
                 final_message += "\n- WARNING: File operation successful, but PR status unclear (no URL and no message)."
             batch_action_results.append({"repo": repo_info.name, "success": True, "message": final_message, "pr_url": None})

    return batch_action_results


def execute_update_file_action(
    g: Github, 
    selected_repo_infos: list[Repository],
    defined_placeholders: list, 
    action_config_from_form: dict, # Contains uf_file_path, uf_update_mode, etc.
    logger: logging.Logger
) -> list[dict]:
    """
    Executes the 'Update/Create File' action.
    action_config_from_form example:
    {
        "file_path": form_values["uf_file_path_input"],
        "branch_name": form_values["uf_branch_name_input"],
        "commit_message": form_values["uf_commit_message_input"],
        "pr_title": form_values["uf_pr_title_input"],
        "pr_body": form_values["uf_pr_body_input"],
        "update_mode": form_values["uf_update_mode"], (e.g. "Replace entire content" or "Search and replace string")
        "file_content": form_values.get("uf_file_content_area"), (if mode is replace)
        "search_string": form_values.get("uf_search_string_input"), (if mode is search/replace)
        "replace_with_string": form_values.get("uf_replace_with_string_input"), (...)
        "is_regex": form_values.get("uf_is_regex_checkbox", False), (...)
        "replace_all": form_values.get("uf_replace_all_checkbox", True), (...)
        "target_path": form_values.get("uf_target_path_input"), # Optional, for targeted search/replace 
        "filename_filter": form_values.get("uf_filename_filter_input") # Optional, for targeted search/replace
    }
    """
    batch_action_results = []
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    # Default branch name template depends on whether it's a single file update or multi-file via find_target_files
    # If uf_file_path_input is present and not empty, it's likely a single file target.
    # Otherwise, it might be a broader update based on target_path/filename_filter.
    # This logic will be refined based on how find_target_files is used.
    # For now, a generic name for the branch seems safer if multiple files might be involved.
    is_single_file_mode = bool(action_config_from_form.get("uf_file_path_input","").strip())
    base_branch_name_action_part = "update-file" if is_single_file_mode else "update-files"
    default_branch_name_template = action_config_from_form.get("uf_branch_name_input", f"{base_branch_name_action_part}-{timestamp_str}")

    repo_api = None # To store g.get_repo(repo_info.full_name) for reuse

    for repo_info in selected_repo_infos:
        action_log_for_repo = [f"Action: Update/Create File(s) on repo {repo_info.full_name} (default branch: {repo_info.default_branch})"]
        logger.info(f"Processing 'Update File' for repo: {repo_info.full_name}")

        try:
            repo_api = g.get_repo(repo_info.full_name) # Get repo object once per repository
        except Exception as e_get_repo:
            action_log_for_repo.append(f"- ERROR: Could not get repository object: {e_get_repo}")
            batch_action_results.append({"repo": repo_info.name, "success": False, "message": "\n".join(action_log_for_repo)})
            continue

        resolved_ph, ph_log, ph_ok = _resolve_all_placeholders_for_repo(g, repo_info, defined_placeholders, timestamp_str, logger)
        action_log_for_repo.extend(ph_log)
        if not ph_ok:
            batch_action_results.append({"repo": repo_info.name, "success": False, "message": "\n".join(action_log_for_repo)})
            continue

        # Common parameters for commit message, PR title/body, and branch name
        current_action_params_for_processing = {
            # file_path will be determined on a per-file basis if find_target_files is used
            # For single file mode, it's action_config_from_form.get("uf_file_path_input")
            # This will be set *inside* the loop over target files for messages.
            "branch_name": default_branch_name_template,
            "commit_message": action_config_from_form.get("uf_commit_message_input"),
            "pr_title": action_config_from_form.get("uf_pr_title_input"),
            "pr_body": action_config_from_form.get("uf_pr_body_input"),
        }
        params_to_reprocess_phase2 = ["branch_name", "commit_message", "pr_title", "pr_body"]
        
        # Resolve placeholders for branch name, commit message, PR title/body *once* per repo if they don't use {{file_path}}
        # If they *do* use {{file_path}}, they will be re-processed per file later.
        # The _process_action_params function now handles two-phase processing correctly.
        
        # Determine target files
        target_files_to_process: list[FileContentResult] = []
        specific_file_path_from_form = action_config_from_form.get("uf_file_path_input", "").strip()

        if specific_file_path_from_form: # Single, specific file path provided
            # Resolve placeholders in this specific file path *first*
            resolved_specific_file_path = process_placeholders_in_string(specific_file_path_from_form, resolved_ph, logger)
            action_log_for_repo.append(f"- INFO: Specific target file path from form '{specific_file_path_from_form}' resolved to '{resolved_specific_file_path}'.")
            if not resolved_specific_file_path:
                action_log_for_repo.append(f"- ERROR: Resolved specific file path is empty. Skipping repo.")
                batch_action_results.append({"repo": repo_info.name, "success": False, "message": "\n".join(action_log_for_repo)})
                continue
            
            # Create a pseudo ContentFile object or fetch it to make the loop consistent
            # For now, let's try to fetch it to confirm existence before creating branch.
            # This also gives us the SHA if it exists, for the update_file call.
            file_content_check_result = github_utils.get_file_content(g, repo_info.full_name, resolved_specific_file_path, repo_info.default_branch)
            if file_content_check_result.error and "not found" not in file_content_check_result.error.lower(): # Error other than not found
                action_log_for_repo.append(f"- WARNING: Could not get initial content/SHA for '{resolved_specific_file_path}' (branch: {repo_info.default_branch}): {file_content_check_result.error}. Will proceed assuming creation or targeted branch later.")
                # We might still proceed if the goal is to create it on a new branch.
                # Create a dummy ContentFile-like object for the loop
                # This is a bit hacky. The update_file function can handle creation if SHA is None.
                # The main thing is to have a .path attribute.
                class DummyContentFile:
                    def __init__(self, path, sha=None):
                        self.path = path
                        self.sha = sha # update_file will fetch if None and file exists on target branch
                target_files_to_process.append(DummyContentFile(path=resolved_specific_file_path, sha=file_content_check_result.sha))
            elif file_content_check_result.sha: # File exists, we have its SHA from default branch
                 action_log_for_repo.append(f"- INFO: Confirmed '{resolved_specific_file_path}' exists on default branch. SHA: {file_content_check_result.sha}. Update will use target branch.")
                 class DummyContentFileWithSha:
                    def __init__(self, path, sha):
                        self.path = path
                        self.sha = sha
                 target_files_to_process.append(DummyContentFileWithSha(path=resolved_specific_file_path, sha=file_content_check_result.sha))
            else: # File not found or other issue that means we treat as potential new file
                action_log_for_repo.append(f"- INFO: File '{resolved_specific_file_path}' not found on default branch or no SHA. Will be treated as new/update on target branch.")
                class DummyContentFileNew:
                    def __init__(self, path):
                        self.path = path
                        self.sha = None # Will be created or SHA fetched from target branch by update_file
                target_files_to_process.append(DummyContentFileNew(path=resolved_specific_file_path))

        else: # Find target files based on criteria (path, filename filter, content query)
            find_files_target_path = process_placeholders_in_string(action_config_from_form.get("uf_target_path_input",""), resolved_ph, logger)
            find_files_filename_filter = process_placeholders_in_string(action_config_from_form.get("uf_filename_filter_input",""), resolved_ph, logger)
            find_files_content_query = process_placeholders_in_string(action_config_from_form.get("uf_content_query_input",""), resolved_ph, logger) # Content query for finding files
            
            action_log_for_repo.append(f"- INFO: Finding target files. Path: '{find_files_target_path}', Filter: '{find_files_filename_filter}', Content Query: '{find_files_content_query}'.")

            if not find_files_filename_filter and not find_files_content_query and not find_files_target_path.strip('/'):
                action_log_for_repo.append(f"- ERROR: For multiple file updates, you must specify at least a target path, a filename filter, or a content query. Skipping repo.")
                batch_action_results.append({"repo": repo_info.name, "success": False, "message": "\n".join(action_log_for_repo)})
                continue
            
            target_files_result = github_utils.find_target_files(
                g, repo_info.full_name, repo_info.default_branch, # Search on default branch initially
                target_path_input=find_files_target_path,
                filename_filter_input=find_files_filename_filter,
                content_query_input=find_files_content_query
            )
            if target_files_result.error:
                action_log_for_repo.append(f"- ERROR: Failed to find target files: {target_files_result.error}. Skipping repo.")
                batch_action_results.append({"repo": repo_info.name, "success": False, "message": "\n".join(action_log_for_repo)})
                continue
            if not target_files_result.files:
                action_log_for_repo.append(f"- INFO: No files found matching criteria. Skipping repo.")
                batch_action_results.append({"repo": repo_info.name, "success": True, "message": "\n".join(action_log_for_repo)})
                continue
            target_files_to_process = target_files_result.files
            action_log_for_repo.append(f"- INFO: Found {len(target_files_to_process)} file(s) to update: {[f.path for f in target_files_to_process]}")

        if not target_files_to_process:
            action_log_for_repo.append(f"- INFO: No files to process after resolving paths/filters. Skipping repo.")
            # This might be success if the intention was conditional and condition not met.
            batch_action_results.append({"repo": repo_info.name, "success": True, "message": "\n".join(action_log_for_repo)})
            continue

        # --- Branch Creation/Verification (once per repo, before looping through files) ---
        # Resolve branch_name placeholder *before* creating/checking the branch
        branch_name_params = {"branch_name": default_branch_name_template}
        resolved_branch_ph_copy = resolved_ph.copy()
        if "file_path" in resolved_branch_ph_copy: # Remove temp file_path for branch name resolution
            del resolved_branch_ph_copy["file_path"]
        
        processed_branch_name_param, bn_log = _process_action_params(branch_name_params, resolved_branch_ph_copy, logger, ["branch_name"])
        action_log_for_repo.extend(bn_log)
        
        # This is the target branch name after placeholder resolution
        target_branch_for_action = processed_branch_name_param.get("branch_name", default_branch_name_template)
        if not target_branch_for_action.strip():
             target_branch_for_action = f"{base_branch_name_action_part}-fallback-{timestamp_str}"
             action_log_for_repo.append(f"- INFO: Target branch name resolved to empty, defaulted to '{target_branch_for_action}'.")

        branch_to_operate_on = target_branch_for_action # This will be the branch used for file ops and PR
        branch_created_this_run = False 

        try:
            logger.info(f"Checking if branch '{target_branch_for_action}' exists in repo '{repo_api.full_name}'.")
            repo_api.get_git_ref(f"heads/{target_branch_for_action}")
            action_log_for_repo.append(f"- INFO: Using existing branch '{target_branch_for_action}'.")
            # If branch exists, we use it as is. No new branch operation needed.
            # branch_op_result can be considered successful for existing branches.
            # No explicit branch_op_result needed here if we proceed directly.
        except github.UnknownObjectException:
            action_log_for_repo.append(f"- INFO: Branch '{target_branch_for_action}' does not exist. Attempting to create it from '{repo_info.default_branch}'.")
            branch_op_result = github_utils.create_branch(g, repo_info.full_name, target_branch_for_action, repo_info.default_branch)
            action_log_for_repo.append(f"- INFO: Branch creation op: {branch_op_result.message}")
            if not branch_op_result.success:
                batch_action_results.append({"repo": repo_info.name, "success": False, "message": "\n".join(action_log_for_repo)})
                continue # Skip to next repo if branch creation fails
            branch_created_this_run = True
        except Exception as e_check_branch:
            action_log_for_repo.append(f"- ERROR: Could not check/create branch '{target_branch_for_action}': {e_check_branch}")
            batch_action_results.append({"repo": repo_info.name, "success": False, "message": "\n".join(action_log_for_repo)})
            continue # Skip to next repo

        # --- End of Branch Creation/Verification ---

        any_file_updated_in_repo = False
        all_file_ops_successful_in_repo = True

        for target_file_obj in target_files_to_process: # target_file_obj is ContentFile or DummyContentFile
            current_file_path = target_file_obj.path
            action_log_for_repo.append(f"---")
            action_log_for_repo.append(f"- INFO: Processing file: '{current_file_path}' on branch '{branch_to_operate_on}'")

            # Prepare parameters for this specific file, including setting {{file_path}} for messages
            # Make a fresh copy of resolved_ph for each file to ensure 'file_path' is specific
            per_file_resolved_ph = resolved_ph.copy()
            per_file_resolved_ph["file_path"] = current_file_path # Set for message processing

            # Resolve placeholders for commit message, PR title, PR body using per_file_resolved_ph
            # These are inside current_action_params_for_processing
            final_commit_msg = process_placeholders_in_string(action_config_from_form.get("uf_commit_message_input"), per_file_resolved_ph, logger)
            # Note: PR title and body are resolved once per repo usually, but if they contain {{file_path}}, 
            # they would need to be aggregated or made generic. For now, we use the last file's context for PR items if {{file_path}} is used.
            # The _process_action_params will use the LATEST value of per_file_resolved_ph["file_path"] for PR items
            # if called after this loop. So, it's better to resolve PR items once, after the loop, if needed.
            # For now, let's assume PR title/body are more generic or use repo-level placeholders.
            # The current structure of _process_action_params means if pr_title/body are in params_to_reprocess_phase2,
            # they get processed with the *last* {{file_path}} from the loop if we call it after. 
            # This is tricky. Let's resolve them with the repo-level placeholders for now and accept that
            # {{file_path}} in PR title/body will be from the last file if not handled carefully.

            # For update_file, we need to resolve content/search/replace strings
            update_mode = action_config_from_form.get("uf_update_mode")
            content_for_update_str = ""
            search_str = None
            replace_str = None

            if update_mode == "Replace entire content":
                raw_content = action_config_from_form.get("uf_file_content_area", "")
                content_for_update_str = process_placeholders_in_string(raw_content, per_file_resolved_ph, logger)
                action_log_for_repo.append(f"- INFO: Update Mode: Replace entire content. Processed content length: {len(content_for_update_str)} chars.")
            elif update_mode == "Search and replace string":
                raw_search = action_config_from_form.get("uf_search_string_input","")
                raw_replace = action_config_from_form.get("uf_replace_with_string_input","")
                search_str = process_placeholders_in_string(raw_search, per_file_resolved_ph, logger)
                replace_str = process_placeholders_in_string(raw_replace, per_file_resolved_ph, logger)
                action_log_for_repo.append(f"- INFO: Update Mode: Search/Replace. Search: '{search_str}', Replace: '{replace_str}', Regex: {action_config_from_form.get('uf_is_regex_checkbox')}, All: {action_config_from_form.get('uf_replace_all_checkbox')}")
                # Get the force_update flag
                force_update_flag = action_config_from_form.get("uc_force_update", False)
                action_log_for_repo.append(f"- INFO: Force update on conflict: {force_update_flag}")
            else:
                action_log_for_repo.append(f"- ERROR: Unknown update mode '{update_mode}' for file '{current_file_path}'. Skipping this file.")
                all_file_ops_successful_in_repo = False
                continue # Skip this file

            # Determine SHA. If it's a DummyContentFile, sha might be None or from default branch.
            # update_file function itself will try to get SHA from the *working_branch_name* if not provided or if it needs to.
            sha_for_update = target_file_obj.sha if hasattr(target_file_obj, 'sha') else None
            action_log_for_repo.append(f"- INFO: SHA for '{current_file_path}' (before update on '{branch_to_operate_on}'): {sha_for_update or 'None (will be fetched/created)'}")

            update_result = github_utils.update_file(
                repo=repo_api, 
                file_path=current_file_path, 
                new_content_str=content_for_update_str, 
                commit_message=final_commit_msg, 
                branch_name=branch_to_operate_on, # Use branch_to_operate_on
                current_sha_from_app=sha_for_update, 
                logger=logger,
                update_mode=update_mode,
                search_string=search_str, 
                replace_with_string=replace_str, 
                is_regex=action_config_from_form.get("uf_is_regex_checkbox", False),
                replace_all=action_config_from_form.get("uf_replace_all_checkbox", True),
                default_branch_for_sr_fallback=repo_info.default_branch, # Pass the default branch here
                force_update=force_update_flag if update_mode == "Search and replace string" else False # Pass the flag
            )

            if update_result.success:
                action_log_for_repo.append(f"- SUCCESS: File '{current_file_path}' processed. {update_result.message} New SHA: {update_result.new_sha}")
                any_file_updated_in_repo = True
            else:
                action_log_for_repo.append(f"- ERROR: Failed to process file '{current_file_path}': {update_result.message}")
                all_file_ops_successful_in_repo = False
                # Optionally, decide if one file failure should stop PR for the whole repo 
                # For now, we continue and will try to PR if any_file_updated_in_repo is true.
        
        action_log_for_repo.append(f"---") # End of file loop for this repo

        if not any_file_updated_in_repo:
            action_log_for_repo.append("- INFO: No files were actually changed in this repository. No PR will be created.")
            # This is a success from the perspective of the batch operation if no errors occurred before this point
            # but no changes were made (e.g. search/replace found no matches).
            batch_action_results.append({"repo": repo_info.name, "success": all_file_ops_successful_in_repo, "message": "\n".join(action_log_for_repo)})
            continue

        # If at least one file was updated, proceed to PR creation
        # Resolve PR title and body again, this time with the *last* file_path in per_file_resolved_ph.
        # This is a known limitation if {{file_path}} is used in PR title/body with multi-file updates.
        # A more robust solution would involve a template for PR body listing all changed files.
        final_pr_title = process_placeholders_in_string(action_config_from_form.get("uf_pr_title_input"), per_file_resolved_ph, logger) # Uses last file's context if {{file_path}} is present
        final_pr_body = process_placeholders_in_string(action_config_from_form.get("uf_pr_body_input"), per_file_resolved_ph, logger)   # Same as above

        action_log_for_repo.append(f"- INFO: Attempting to create PR from '{branch_to_operate_on}' to '{repo_info.default_branch}'. Title: '{final_pr_title}'")
        pr_result = github_utils.create_pull_request(
            g, repo_info.full_name, branch_to_operate_on, repo_info.default_branch, # Use branch_to_operate_on
            final_pr_title, final_pr_body
        )
        action_log_for_repo.append(f"- INFO: PR creation: {pr_result.message or ('Success' if pr_result.html_url else 'Failed/Already Exists with no new URL')}")
        
        repo_overall_success = all_file_ops_successful_in_repo and bool(pr_result.html_url) 
        # If all file ops were good, but PR failed, repo is success=true but with a warning in message.
        # If any file op failed, repo is success=false.

        final_repo_message = "\n".join(action_log_for_repo)
        if not all_file_ops_successful_in_repo:
            final_repo_message += "\n- WARNING: One or more file operations failed. See logs above."
            repo_overall_success = False # Ensure overall success is false if any file op failed
        elif not pr_result.html_url and pr_result.message:
            final_repo_message += f"\n- WARNING: File operations successful, but PR issue: {pr_result.message}"
            # Keep repo_overall_success based on all_file_ops_successful_in_repo, as PR might just exist

        batch_action_results.append({
            "repo": repo_info.name, 
            "success": repo_overall_success, # True only if all files ok AND PR ok (or PR already existed)
            "message": final_repo_message,
            "pr_url": pr_result.html_url
        })

    return batch_action_results


def execute_add_new_file_action(
    g: Github, 
    selected_repo_infos: list[Repository],
    defined_placeholders: list, 
    action_config_from_form: dict, # Contains anf_file_path, anf_file_content, etc.
    logger: logging.Logger
) -> list[dict]:
    """
    Executes the 'Add New File' action.
    action_config_from_form example:
    {
        "file_path": form_values["anf_file_path_input"],
        "file_content": form_values["anf_file_content_area"],
        "branch_name": form_values["anf_branch_name_input"],
        "commit_message": form_values["anf_commit_message_input"],
        "pr_title": form_values["anf_pr_title_input"],
        "pr_body": form_values["anf_pr_body_input"]
    }
    """
    batch_action_results = []
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    default_branch_name_template = action_config_from_form.get("anf_branch_name_input", f"add-file-{timestamp_str}")

    for repo_info in selected_repo_infos:
        action_log_for_repo = [f"Action: Add New File on repo {repo_info.full_name} (default branch: {repo_info.default_branch})"]
        logger.info(f"Processing 'Add New File' for repo: {repo_info.full_name}")

        resolved_ph, ph_log, ph_ok = _resolve_all_placeholders_for_repo(g, repo_info, defined_placeholders, timestamp_str, logger)
        action_log_for_repo.extend(ph_log)
        if not ph_ok:
            batch_action_results.append({"repo": repo_info.name, "success": False, "message": "\n".join(action_log_for_repo)})
            continue
        
        # Prepare parameters for _process_action_params
        current_action_params_for_processing = {
            "file_path": action_config_from_form.get("anf_file_path_input"),
            "file_content": action_config_from_form.get("anf_file_content_area"),
            "branch_name": default_branch_name_template,
            "commit_message": action_config_from_form.get("anf_commit_message_input"),
            "pr_title": action_config_from_form.get("anf_pr_title_input"),
            "pr_body": action_config_from_form.get("anf_pr_body_input")
        }
        params_to_reprocess_phase2 = ["file_path", "file_content", "branch_name", "commit_message", "pr_title", "pr_body"]
        
        processed_params, params_log = _process_action_params(current_action_params_for_processing, resolved_ph, logger, params_to_reprocess_phase2)
        action_log_for_repo.extend(params_log)

        target_file_path = processed_params.get("file_path", "")
        new_file_content = processed_params.get("file_content", "")
        
        # Resolve target branch name
        target_branch_for_action = processed_params.get("branch_name", default_branch_name_template)
        if not target_branch_for_action or not target_branch_for_action.strip():
            target_branch_for_action = f"add-file-fallback-{timestamp_str}"
            action_log_for_repo.append(f"- INFO: Target branch name was empty or invalid, defaulted to '{target_branch_for_action}'.")

        branch_to_operate_on = target_branch_for_action
        branch_created_this_run = False

        if not target_file_path:
            action_log_for_repo.append(f"- ERROR: Processed file path is empty. Skipping repo.")
            batch_action_results.append({"repo": repo_info.name, "success": False, "message": "\n".join(action_log_for_repo)})
            continue
        
        repo_api = None # Defined here, will be assigned in the try block
        try:
            repo_api = g.get_repo(repo_info.full_name)
            logger.info(f"Checking if branch '{target_branch_for_action}' exists in repo '{repo_api.full_name}'.")
            repo_api.get_git_ref(f"heads/{target_branch_for_action}")
            action_log_for_repo.append(f"- INFO: Using existing branch '{target_branch_for_action}'.")
        except github.UnknownObjectException:
            action_log_for_repo.append(f"- INFO: Branch '{target_branch_for_action}' does not exist. Attempting to create it from '{repo_info.default_branch}'.")
            # Ensure repo_api is available for create_branch if it was not assigned due to early UnknownObjectException
            if repo_api is None: # Should ideally be caught by the outer repo_api assignment, but as a safeguard
                 repo_api = g.get_repo(repo_info.full_name) # Re-assign if needed before create_branch
            branch_op_result = github_utils.create_branch(g, repo_info.full_name, target_branch_for_action, repo_info.default_branch)
            action_log_for_repo.append(f"- INFO: Branch creation op: {branch_op_result.message}")
            if not branch_op_result.success:
                batch_action_results.append({"repo": repo_info.name, "success": False, "message": "\n".join(action_log_for_repo)})
                continue
            branch_created_this_run = True
        except Exception as e_check_branch:
            err_msg_check_branch = f"Could not check/create branch '{target_branch_for_action}': {e_check_branch}"
            if repo_api is None: # If g.get_repo itself failed
                err_msg_check_branch = f"Could not get repository object for branch check. Original error: {e_check_branch}"
            action_log_for_repo.append(f"- ERROR: {err_msg_check_branch}")
            batch_action_results.append({"repo": repo_info.name, "success": False, "message": "\n".join(action_log_for_repo)})
            continue

        # For adding a new file, we use update_file with sha=None (or current_sha_from_app=None)
        action_log_for_repo.append(f"- INFO: Attempting to add file '{target_file_path}' on branch '{branch_to_operate_on}'.")
        
        # Ensure repo_api is valid if not already set (e.g. if branch existed)
        if repo_api is None:
            try:
                repo_api = g.get_repo(repo_info.full_name)
            except Exception as e_get_repo_late:
                action_log_for_repo.append(f"- ERROR: Could not get repository object for adding file: {e_get_repo_late}")
                batch_action_results.append({"repo": repo_info.name, "success": False, "message": "\n".join(action_log_for_repo)})
                continue

        add_file_result = github_utils.update_file(
            repo=repo_api, 
            file_path=target_file_path, 
            new_content_str=new_file_content, 
            commit_message=processed_params["commit_message"],
            branch_name=branch_to_operate_on,
            current_sha_from_app=None, # Explicitly None for creation
            logger=logger,
            update_mode="Replace entire content", # Adding a new file is like replacing entire (non-existent) content
            force_update=False # Force update is not applicable to add new file in this context
        )

        if add_file_result.success:
            action_log_for_repo.append(f"- SUCCESS: File '{target_file_path}' added. {add_file_result.message} New SHA: {add_file_result.new_sha}")
        else:
            action_log_for_repo.append(f"- ERROR: Failed to add file '{target_file_path}': {add_file_result.message}")
            batch_action_results.append({"repo": repo_info.name, "success": False, "message": "\n".join(action_log_for_repo)})
            continue # Skip PR creation if file add failed

        # Proceed to PR creation
        pr_result = github_utils.create_pull_request(
            g, repo_info.full_name, branch_to_operate_on, repo_info.default_branch,
            processed_params["pr_title"], processed_params["pr_body"]
        )
        action_log_for_repo.append(f"- INFO: PR creation: {pr_result.message or ('Success' if pr_result.html_url else 'Failed/Already Exists with no new URL')}")

        final_repo_message = "\n".join(action_log_for_repo)
        repo_overall_success = add_file_result.success and bool(pr_result.html_url)
        
        if not add_file_result.success: # Should have been caught by continue, but for safety
            final_repo_message += "\n- WARNING: File add operation failed. See logs above."
            repo_overall_success = False
        elif not pr_result.html_url and pr_result.message:
             final_repo_message += f"\n- WARNING: File add successful, but PR issue: {pr_result.message}"
        
        batch_action_results.append({
            "repo": repo_info.name, 
            "success": repo_overall_success, 
            "message": final_repo_message,
            "pr_url": pr_result.html_url
        })

    return batch_action_results 