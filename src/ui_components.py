import streamlit as st
import datetime # Potentially for timestamp, if needed in UI components
from . import github_utils # Changed to relative import
from github import Github # Added for Github instance during testing
# Import github_utils and other necessary modules if the components require them
# For example, for accessing session_state or specific functions.
import logging
from typing import Callable, List, Dict, Any, Optional

# Global variable for placeholder methods to make it available
# This variable is also defined in app.py, consider centralizing or passing as an argument
NEW_PLACEHOLDER_METHOD_OPTIONS = ["Regex", "JSON Path", "YAML Path"]

def render_placeholder_definition_ui(logger, access_token, repositories_data, selected_repos_urls):
    """
    Renders the UI for defining and editing dynamic placeholders.
    Requires logger, access_token, and repositories_data for testing.
    'selected_repos_urls' is a set of HTML URLs of the selected repositories.
    """
    st.markdown("Define placeholders that can be used in action parameters like `{{placeholder_name}}`. Values are extracted from files in each repository.")
    
    col_method_selection, _ = st.columns([1, 2]) 
    with col_method_selection:
        def on_placeholder_method_selection_change_ui_component():
            new_method_value = st.session_state.ph_method_selector_key_outside_form_comp
            st.session_state.selected_ph_method_for_ui = new_method_value
            try:
                st.session_state.selected_ph_method_index_for_ui = NEW_PLACEHOLDER_METHOD_OPTIONS.index(new_method_value)
            except ValueError:
                st.session_state.selected_ph_method_index_for_ui = 0 
                st.session_state.selected_ph_method_for_ui = NEW_PLACEHOLDER_METHOD_OPTIONS[0]
        
        st.selectbox(
            "Extraction Method", 
            NEW_PLACEHOLDER_METHOD_OPTIONS, 
            index=st.session_state.selected_ph_method_index_for_ui, 
            key="ph_method_selector_key_outside_form_comp", # Changed key to prevent collision
            on_change=on_placeholder_method_selection_change_ui_component
        )
    
    form_submit_button_label = "Save Placeholder"

    if st.session_state.editing_placeholder_index is not None and not st.session_state.placeholder_form_values_loaded_for_edit:
        ph_to_edit = st.session_state.placeholders[st.session_state.editing_placeholder_index]
        st.session_state.ph_form_name = ph_to_edit.get("name", "")
        st.session_state.ph_form_file_path = ph_to_edit.get("file_path", "")
        
        method_to_load = ph_to_edit.get("method", NEW_PLACEHOLDER_METHOD_OPTIONS[0])
        st.session_state.selected_ph_method_for_ui = method_to_load 
        try:
            st.session_state.selected_ph_method_index_for_ui = NEW_PLACEHOLDER_METHOD_OPTIONS.index(method_to_load)
        except ValueError:
            st.session_state.selected_ph_method_index_for_ui = 0 
            st.session_state.selected_ph_method_for_ui = NEW_PLACEHOLDER_METHOD_OPTIONS[0] 
        
        config = ph_to_edit.get("config", {})
        if st.session_state.selected_ph_method_for_ui == "Regex":
            st.session_state.ph_form_regex_pattern = config.get("pattern", "")
            st.session_state.ph_form_regex_group = config.get("group_index", 1)
        else:
            st.session_state.ph_form_regex_pattern = "" 
            st.session_state.ph_form_regex_group = 1
        if st.session_state.selected_ph_method_for_ui == "JSON Path":
            st.session_state.ph_form_jsonpath = config.get("jsonpath_expression", "")
        else:
            st.session_state.ph_form_jsonpath = ""
        if st.session_state.selected_ph_method_for_ui == "YAML Path":
            yaml_path_to_load = config.get("yaml_path", "")
            if isinstance(yaml_path_to_load, list):
                st.session_state.ph_form_yamlpath = "\n".join(yaml_path_to_load)
            else: 
                st.session_state.ph_form_yamlpath = yaml_path_to_load
        else:
            st.session_state.ph_form_yamlpath = ""
        st.session_state.form_placeholder_test_result_content = None 
        st.session_state.placeholder_form_values_loaded_for_edit = True 
        st.rerun() # Rerun to reflect loaded values in widgets controlled by session_state

    # Initialize form field states if they don't exist (e.g. on first run or after clearing)
    if "ph_form_name" not in st.session_state: st.session_state.ph_form_name = ""
    if "ph_form_file_path" not in st.session_state: st.session_state.ph_form_file_path = ""
    if "ph_form_regex_pattern" not in st.session_state: st.session_state.ph_form_regex_pattern = ""
    if "ph_form_regex_group" not in st.session_state: st.session_state.ph_form_regex_group = 1
    if "ph_form_jsonpath" not in st.session_state: st.session_state.ph_form_jsonpath = ""
    if "ph_form_yamlpath" not in st.session_state: st.session_state.ph_form_yamlpath = ""

    col1_form, col2_form = st.columns(2)
    with col1_form:
        st.session_state.ph_form_name = st.text_input("Placeholder Name", value=st.session_state.ph_form_name, key="ph_widget_name_comp")
    with col2_form:
        st.session_state.ph_form_file_path = st.text_input("Source File Path in Repo", value=st.session_state.ph_form_file_path, key="ph_widget_file_path_comp")

    st.markdown("**Method Specific Configuration:**")
    if st.session_state.selected_ph_method_for_ui == "Regex":
        st.session_state.ph_form_regex_pattern = st.text_input("Regex Pattern", value=st.session_state.ph_form_regex_pattern, key="ph_widget_regex_pattern_comp")
        st.session_state.ph_form_regex_group = st.number_input("Regex Group Index", min_value=0, step=1, value=st.session_state.ph_form_regex_group, key="ph_widget_regex_group_comp")
    elif st.session_state.selected_ph_method_for_ui == "JSON Path":
        st.session_state.ph_form_jsonpath = st.text_input("JSONPath Expression", value=st.session_state.ph_form_jsonpath, key="ph_widget_jsonpath_comp")
    elif st.session_state.selected_ph_method_for_ui == "YAML Path":
        st.session_state.ph_form_yamlpath = st.text_area(
            "YAML Path(s) (one per line)", 
            value=st.session_state.ph_form_yamlpath, 
            key="ph_widget_yamlpath_comp",
            help="Enter one YAML path per line. The system will try them in order and use the first one that returns a value."
        )
    
    if st.button("🧪 Test Current Settings", key="test_current_settings_trigger_button_comp"):
        temp_ph_name = st.session_state.get("ph_form_name", "")
        temp_ph_file_path = st.session_state.get("ph_form_file_path", "")
        temp_ph_method = st.session_state.selected_ph_method_for_ui 
        temp_ph_config = {}
        valid_for_test = True

        if not temp_ph_name or not temp_ph_file_path:
            st.session_state.form_placeholder_test_result_content = ("warning", "Placeholder Name and Source File Path are required to run a test.")
            valid_for_test = False
        
        if valid_for_test:
            if temp_ph_method == "Regex":
                temp_ph_config["pattern"] = st.session_state.get("ph_form_regex_pattern", "")
                temp_ph_config["group_index"] = st.session_state.get("ph_form_regex_group", 1)
                if not temp_ph_config["pattern"]:
                    st.session_state.form_placeholder_test_result_content = ("warning", "Regex Pattern is required for Regex method test.")
                    valid_for_test = False
            elif temp_ph_method == "JSON Path":
                temp_ph_config["jsonpath_expression"] = st.session_state.get("ph_form_jsonpath", "")
                if not temp_ph_config["jsonpath_expression"]:
                    st.session_state.form_placeholder_test_result_content = ("warning", "JSONPath Expression is required for JSON Path method test.")
                    valid_for_test = False
            elif temp_ph_method == "YAML Path":
                yaml_path_input = st.session_state.get("ph_form_yamlpath", "")
                temp_ph_config["yaml_path"] = [path.strip() for path in yaml_path_input.split('\n') if path.strip()]
                if not temp_ph_config["yaml_path"]:
                    st.session_state.form_placeholder_test_result_content = ("warning", "YAML Path is required for YAML Path method test.")
                    valid_for_test = False

        if valid_for_test:
            if not selected_repos_urls:
                st.session_state.form_placeholder_test_result_content = ("warning", "Please select at least one repository in Tab 1 to test placeholder configuration.")
            else:
                first_selected_repo_html_url = next(iter(selected_repos_urls), None)
                if not first_selected_repo_html_url or not repositories_data:
                    st.session_state.form_placeholder_test_result_content = ("error", "Could not retrieve the first selected repository for testing (no URL or no repo data).")
                else:
                    test_repo_info = next((repo for repo in repositories_data if repo.html_url == first_selected_repo_html_url), None)
                    if not test_repo_info or not hasattr(test_repo_info, 'full_name') or not hasattr(test_repo_info, 'default_branch'):
                        st.session_state.form_placeholder_test_result_content = ("error", f"Failed to get valid repository info for testing for: {first_selected_repo_html_url}")
                    else:
                        with st.spinner(f"Testing placeholder '{temp_ph_name}' on {test_repo_info.name}..."):
                            try:
                                g_test = Github(access_token)
                                # Here we call placeholder_extraction_result, not directly extract_placeholder_value
                                # and expect a (value, error) tuple
                                result = github_utils.extract_placeholder_value( # result is PlaceholderExtractionResult
                                    g_test, test_repo_info.full_name, test_repo_info.default_branch, 
                                    temp_ph_file_path, temp_ph_method, temp_ph_config,
                                    logger
                                )
                                if result.error:
                                    st.session_state.form_placeholder_test_result_content = ("error", f"Error: {result.error}")
                                elif result.value is None: # Explicitly None value is a success, but we display it differently
                                    st.session_state.form_placeholder_test_result_content = ("info", f"Extracted value is `None`.")
                                else:
                                    st.session_state.form_placeholder_test_result_content = ("success", f"Extracted Value: '{result.value}'")
                            except Exception as e:
                                logger.error(f"Exception during placeholder test for '{temp_ph_name}': {e}", exc_info=True)
                                st.session_state.form_placeholder_test_result_content = ("error", f"Test Exception: {e}")
        st.rerun()
    
    if st.session_state.form_placeholder_test_result_content:
        status, message = st.session_state.form_placeholder_test_result_content
        if status == "success": st.success(message)
        elif status == "info": st.info(message)
        elif status == "warning": st.warning(message)
        elif status == "error": st.error(message)
        st.markdown("---")

    if st.button(form_submit_button_label, key="save_or_update_placeholder_button_comp"):
        st.session_state.form_placeholder_test_result_content = None 
        ph_name_val = st.session_state.ph_form_name
        ph_file_path_val = st.session_state.ph_form_file_path
        
        if ph_name_val and ph_file_path_val:
            current_config_to_store = {}
            valid_config = True
            submission_method = st.session_state.selected_ph_method_for_ui 

            if submission_method == "Regex":
                pattern = st.session_state.ph_form_regex_pattern
                group_index = st.session_state.ph_form_regex_group
                if not pattern:
                    st.error("Regex Pattern is required for Regex method.")
                    valid_config = False
                else:
                    current_config_to_store["pattern"] = pattern
                    current_config_to_store["group_index"] = group_index
            elif submission_method == "JSON Path":
                jsonpath_expression = st.session_state.ph_form_jsonpath
                if not jsonpath_expression:
                    st.error("JSONPath Expression is required for JSON Path method.")
                    valid_config = False
                else:
                    current_config_to_store["jsonpath_expression"] = jsonpath_expression
            elif submission_method == "YAML Path":
                yaml_path_input_str = st.session_state.ph_form_yamlpath
                list_of_yaml_paths = [path.strip() for path in yaml_path_input_str.split('\n') if path.strip()]
                if not list_of_yaml_paths:
                    st.error("YAML Path is required for YAML Path method.")
                    valid_config = False
                else:
                    current_config_to_store["yaml_path"] = list_of_yaml_paths
            
            if valid_config:
                new_placeholder_data = {
                    "name": ph_name_val,
                    "file_path": ph_file_path_val,
                    "method": submission_method, 
                    "config": current_config_to_store,
                }
                if st.session_state.editing_placeholder_index is not None:
                    st.session_state.placeholders[st.session_state.editing_placeholder_index] = new_placeholder_data
                    st.success(f"Placeholder '{ph_name_val}' updated!")
                    st.session_state.editing_placeholder_index = None 
                else:
                    st.session_state.placeholders.append(new_placeholder_data)
                    st.success(f"Placeholder '{ph_name_val}' added!")
                
                # Reset form fields and method selection
                st.session_state.ph_form_name = ""
                st.session_state.ph_form_file_path = ""
                st.session_state.ph_form_regex_pattern = ""
                st.session_state.ph_form_regex_group = 1
                st.session_state.ph_form_jsonpath = ""
                st.session_state.ph_form_yamlpath = ""
                st.session_state.selected_ph_method_index_for_ui = 0
                st.session_state.selected_ph_method_for_ui = NEW_PLACEHOLDER_METHOD_OPTIONS[st.session_state.selected_ph_method_index_for_ui]
                st.session_state.form_placeholder_test_result_content = None 
                st.session_state.placeholder_form_values_loaded_for_edit = False 
                st.rerun()
        else: 
            if not ph_name_val: st.error("Placeholder Name is required.")
            if not ph_file_path_val: st.error("Source File Path is required.")

    if st.session_state.editing_placeholder_index is not None:
        if st.button("Cancel Edit", key="cancel_edit_ph_button_comp"):
            st.session_state.editing_placeholder_index = None
            st.session_state.placeholder_form_values_loaded_for_edit = False
            st.session_state.ph_form_name = ""
            st.session_state.ph_form_file_path = ""
            st.session_state.ph_form_regex_pattern = ""
            st.session_state.ph_form_regex_group = 1
            st.session_state.ph_form_jsonpath = ""
            st.session_state.ph_form_yamlpath = ""
            st.session_state.selected_ph_method_index_for_ui = 0
            st.session_state.selected_ph_method_for_ui = NEW_PLACEHOLDER_METHOD_OPTIONS[st.session_state.selected_ph_method_index_for_ui]
            st.session_state.form_placeholder_test_result_content = None 
            st.session_state.placeholder_form_values_loaded_for_edit = False
            st.rerun()

def render_defined_placeholders_list(logger, access_token, repositories_data, selected_repos_urls):
    """
    Renders the list of currently defined placeholders with options to edit or remove them.
    A test button for each placeholder is also included.
    """
    if st.session_state.placeholders:
        st.markdown("---")
        st.subheader("Defined Placeholders")
        
        for i, ph in enumerate(st.session_state.placeholders):
            ph_name = ph.get("name", "N/A")
            ph_method = ph.get("method", "N/A")
            ph_file = ph.get("file_path", "N/A")
            
            col1, col2, col3, col4 = st.columns([3,2,2,1]) # Added fourth column for Test button
            with col1:
                st.markdown(f"**{ph_name}**")
                st.caption(f"File: `{ph_file}`")
            with col2:
                st.markdown(f"Method: `{ph_method}`")
                config_str = ", ".join([f"{k}: {v}" for k,v in ph.get("config", {}).items()])
                st.caption(f"Config: `{config_str}`")

            with col3: # Edit and Remove buttons
                if st.button(f"Edit Placeholder", key=f"edit_ph_{i}_comp"):
                    st.session_state.editing_placeholder_index = i
                    st.session_state.placeholder_form_values_loaded_for_edit = False # Trigger load
                    st.session_state.form_placeholder_test_result_content = None # Clear previous test results
                    st.rerun()
                if st.button(f"Remove Placeholder", key=f"remove_ph_{i}_comp"):
                    removed_ph_name = st.session_state.placeholders.pop(i).get("name", "Unknown")
                    st.success(f"Placeholder '{removed_ph_name}' removed.")
                    if st.session_state.editing_placeholder_index == i:
                        st.session_state.editing_placeholder_index = None
                        st.session_state.placeholder_form_values_loaded_for_edit = False
                        # Reset form fields explicitly if the one being edited is removed
                        st.session_state.ph_form_name = ""
                        st.session_state.ph_form_file_path = ""
                        st.session_state.ph_form_regex_pattern = ""
                        st.session_state.ph_form_regex_group = 1
                        st.session_state.ph_form_jsonpath = ""
                        st.session_state.ph_form_yamlpath = ""
                        st.session_state.selected_ph_method_index_for_ui = 0
                        st.session_state.selected_ph_method_for_ui = NEW_PLACEHOLDER_METHOD_OPTIONS[0]
                        st.session_state.form_placeholder_test_result_content = None

                    elif st.session_state.editing_placeholder_index is not None and i < st.session_state.editing_placeholder_index:
                        st.session_state.editing_placeholder_index -=1 
                    st.rerun()

            with col4: # Test button
                 # Unique key for test results in session state
                test_result_key = f"test_result_ph_{i}"
                if st.button(f"🧪 Test", key=f"test_single_ph_{i}_comp"):
                    if not selected_repos_urls:
                        st.session_state[test_result_key] = ("warning", "Select a repo in Tab 1 to test.")
                    else:
                        first_selected_repo_html_url = next(iter(selected_repos_urls), None)
                        test_repo_info = next((repo for repo in repositories_data if repo.html_url == first_selected_repo_html_url), None)

                        if not test_repo_info or not hasattr(test_repo_info, 'full_name') or not hasattr(test_repo_info, 'default_branch'):
                            st.session_state[test_result_key] = ("error", "Failed to get valid repository info for testing.")
                        else:
                            with st.spinner(f"Testing '{ph_name}' on {test_repo_info.name}..."):
                                try:
                                    g_test_single = Github(access_token)
                                    # Expect PlaceholderExtractionResult
                                    result = github_utils.extract_placeholder_value(
                                        g_test_single, test_repo_info.full_name, test_repo_info.default_branch,
                                        ph.get("file_path"), ph.get("method"), ph.get("config", {}),
                                        logger
                                    )
                                    if result.error:
                                        st.session_state[test_result_key] = ("error", f"Error: {result.error}")
                                    elif result.value is None:
                                        st.session_state[test_result_key] = ("info", "Extracted value is `None`.")
                                    else:
                                        st.session_state[test_result_key] = ("success", f"Value: '{result.value}'")
                                except Exception as e:
                                    logger.error(f"Exception during single placeholder test for '{ph_name}': {e}", exc_info=True)
                                    st.session_state[test_result_key] = ("error", f"Exception: {e}")
                    st.rerun() # Rerun to show the test result

            # Display test result if available
            if test_result_key in st.session_state and st.session_state[test_result_key]:
                status, message = st.session_state[test_result_key]
                if status == "success": st.success(message)
                elif status == "info": st.info(message)
                elif status == "warning": st.warning(message)
                elif status == "error": st.error(message)
            st.markdown("---") # Separator for each placeholder entry

def render_remove_file_form(timestamp_str: str):
    """Renders the form for the 'Remove File' action."""
    with st.form(key="remove_file_form"):
        st.markdown("##### 📄 Specify File and Commit Details")
        rf_file_path = st.text_input("File Path to Remove", key="rf_file_path_input_widget", placeholder="path/to/your/file.txt", help="Path to the file to be removed (e.g., `src/old_module.py`). Placeholders can be used.")
        
        st.markdown("---")
        st.markdown("##### 🌳 Branch, Commit, and Pull Request")
        rf_branch_name = st.text_input("New Branch Name", key="rf_branch_name_input_widget", help="Name for the new branch. Placeholders like {{file_path}} can be used. If blank, a generic name will be used.")
        rf_commit_message = st.text_input("Commit Message", value="Remove {{file_path}}", key="rf_commit_message_input_widget", help="Commit message. `{{file_path}}` (resolved path of the file being removed) and other placeholders can be used.")
        rf_pr_title = st.text_input("Pull Request Title", value="Remove {{file_path}}", key="rf_pr_title_input_widget", help="Title for the Pull Request. Placeholders can be used.")
        rf_pr_body = st.text_area("Pull Request Body", value="This PR removes `{{file_path}}`.", key="rf_pr_body_input_widget", help="Body for the Pull Request. Placeholders can be used.")
        
        submitted = st.form_submit_button("🚀 Execute Remove File Action", use_container_width=True)
        if submitted:
            form_data = {
                "rf_file_path": rf_file_path,
                "rf_branch_name": rf_branch_name,
                "rf_commit_message": rf_commit_message,
                "rf_pr_title": rf_pr_title,
                "rf_pr_body": rf_pr_body,
            }
            return True, form_data
    return False, None

def render_update_file_form(timestamp_str: str):
    """Renders the form for the 'Update/Create File' action."""

    # Callback for update mode radio
    def on_update_mode_change_comp():
        st.session_state.uf_selected_update_mode = st.session_state.uf_update_mode_radio_key_comp
        # Reset conditional fields if mode changes to ensure clean state
        if st.session_state.uf_selected_update_mode == "Replace entire content":
            st.session_state.uf_search_string_input = ""
            st.session_state.uf_replace_with_string_input = ""
            # uf_file_content_area is always visible for "Replace" mode.
        elif st.session_state.uf_selected_update_mode == "Search and replace string":
            st.session_state.uf_file_content_area = "" # Clear content area if switching to S&R
    
    # Initialize session state for update mode if not present
    if "uf_selected_update_mode" not in st.session_state:
        st.session_state.uf_selected_update_mode = "Replace entire content" # Default
    if "uf_file_path_input" not in st.session_state: st.session_state.uf_file_path_input = ""
    if "uf_file_content_area" not in st.session_state: st.session_state.uf_file_content_area = ""
    if "uf_search_string_input" not in st.session_state: st.session_state.uf_search_string_input = ""
    if "uf_replace_with_string_input" not in st.session_state: st.session_state.uf_replace_with_string_input = ""
    if "uf_is_regex_checkbox" not in st.session_state: st.session_state.uf_is_regex_checkbox = False
    if "uf_replace_all_checkbox" not in st.session_state: st.session_state.uf_replace_all_checkbox = True
    if "uf_target_path_input" not in st.session_state: st.session_state.uf_target_path_input = ""
    if "uf_filename_filter_input" not in st.session_state: st.session_state.uf_filename_filter_input = ""
    if "uf_content_query_input" not in st.session_state: st.session_state.uf_content_query_input = ""

    # Add the st.radio for selecting update mode - THIS STAYS OUTSIDE THE FORM
    st.radio(
        "Update Mode:",
        options=["Replace entire content", "Search and replace string"],
        key="uf_update_mode_radio_key_comp", # Key used by the on_update_mode_change_comp callback
        on_change=on_update_mode_change_comp,
        horizontal=True,
        index=["Replace entire content", "Search and replace string"].index(st.session_state.uf_selected_update_mode) # Set index based on current session state
    )

    # WRAP THE REST OF THE FORM ELEMENTS, INCLUDING THE SUBMIT BUTTON, IN st.form
    with st.form(key="update_create_file_form"): # ADDED st.form HERE
        st.markdown("##### 📄 Specify File and Update Mode") # This title can be inside the form
        st.session_state.uf_file_path_input = st.text_input( # Ensure this uses session_state for value persistence
            "File Path to Update/Create",
            value=st.session_state.uf_file_path_input, # Read from session state
            key="uc_file_path_input_widget_form", # Ensure key is unique if similar widget exists elsewhere
            placeholder="path/to/your/file.txt",
            help="Path to the file. If it exists, it will be updated. If not, it will be created. Placeholders can be used."
        )
        
        # Get the current mode from session state for conditional UI
        current_update_mode = st.session_state.uf_selected_update_mode # CORRECTED KEY

        # Initialize variables that will be returned or used by the form
        uc_content = ""
        uc_search_string = ""
        uc_replace_string = ""
        uc_use_regex_search = False 
        uc_force_update = False # Initialize to False, will be set by checkbox if mode is correct

        # Key for session state for the force update checkbox value
        force_update_session_key = "uc_force_update_val"
        if force_update_session_key not in st.session_state:
            st.session_state[force_update_session_key] = False # Default to False

        if current_update_mode == "Replace entire content":
            uc_content = st.text_area(
                "New Content",
                height=200,
                key="uc_content_input_widget",
                placeholder="Enter the full new content of the file. Placeholders can be used.",
                help="The entire content for the file. If the file exists, its content will be replaced. If not, a new file with this content will be created."
            )
            # Ensure force_update is False if not in search_and_replace mode
            st.session_state[force_update_session_key] = False
            uc_force_update = False

        elif current_update_mode == "Search and replace string":
            st.markdown("Define search and replacement patterns:")
            col_sr1, col_sr2 = st.columns(2)
            with col_sr1:
                uc_search_string = st.text_input("Search String/Regex", key="uc_search_input_widget", help="The string or regex pattern to search for. Placeholders can be used.")
            with col_sr2:
                uc_replace_string = st.text_input("Replacement String", key="uc_replace_input_widget", help="The string to replace the found occurrences with. Placeholders can be used. For regex, use group references like \\1, \\2.")
            
            uc_use_regex_search = st.checkbox("Use regex for search", key="uc_use_regex_widget", help="If checked, the search string will be treated as a regular expression.")
            
            # "Force update" checkbox specific to "Search and replace string" mode
            st.session_state[force_update_session_key] = st.checkbox(
                "Force update (overwrite on conflict)", 
                value=st.session_state[force_update_session_key],
                key="uc_force_update_checkbox_widget", # Unique key for the checkbox widget itself
                help="If checked and a SHA conflict (409) occurs, the system will attempt to delete the existing file and then create it with the modified content. Use with caution."
            )
            uc_force_update = st.session_state[force_update_session_key]

        st.markdown("---")
        st.markdown("##### 🌳 Branch, Commit, and Pull Request")
        st.session_state.uf_branch_name_input = st.text_input("New Branch Name", value=st.session_state.get("uf_branch_name_input", f"update-file-{timestamp_str}"), key="uf_branch_name_input_widget", help="Name for the new branch. Placeholders can be used. `{{timestamp}}` is available.")
        st.session_state.uf_commit_message_input = st.text_input("Commit Message", value=st.session_state.get("uf_commit_message_input", "Update {{file_path}}"), key="uf_commit_message_input_widget", help="Commit message. `{{file_path}}` (resolved path of the file being updated/created) and other placeholders can be used.")
        st.session_state.uf_pr_title_input = st.text_input("Pull Request Title", value=st.session_state.get("uf_pr_title_input", "Update {{file_path}}"), key="uf_pr_title_input_widget", help="Title for the Pull Request. Placeholders can be used.")
        st.session_state.uf_pr_body_input = st.text_area("Pull Request Body", value=st.session_state.get("uf_pr_body_input", "This PR updates `{{file_path}}`."), key="uf_pr_body_input_widget", help="Body for the Pull Request. Placeholders can be used.")

        submitted = st.form_submit_button("🚀 Execute Update/Create File Action", use_container_width=True)
        if submitted:
            form_data = {
                "uf_file_path_input": st.session_state.uf_file_path_input,
                "uf_update_mode": st.session_state.uf_selected_update_mode, 
                "uf_file_content_area": uc_content, # Use local var for content (relevant for "Replace" mode)
                "uf_search_string_input": uc_search_string, # Use local var for search string
                "uf_replace_with_string_input": uc_replace_string, # Use local var for replace string
                "uf_is_regex_checkbox": uc_use_regex_search, # Use local var for regex flag
                # uf_replace_all_checkbox is not used by uc_ variables, directly use session_state or ensure it's set
                "uf_replace_all_checkbox": st.session_state.get("uf_replace_all_checkbox", True), # Assuming this is managed by a checkbox with this key
                
                # These seem to be legacy/unused or for a different feature (find_target_files) that was removed/changed.
                # If they are still intended to be part of this form, their widgets need to be present.
                # For now, let's ensure they default to empty strings if not explicitly set by a widget in this form.
                "uf_target_path_input": st.session_state.get("uf_target_path_input", ""),
                "uf_filename_filter_input": st.session_state.get("uf_filename_filter_input", ""),
                "uf_content_query_input": st.session_state.get("uf_content_query_input", ""),
                
                "uf_branch_name_input": st.session_state.uf_branch_name_input, # Read from session_state, set by text_input above
                "uf_commit_message_input": st.session_state.uf_commit_message_input, 
                "uf_pr_title_input": st.session_state.uf_pr_title_input, 
                "uf_pr_body_input": st.session_state.uf_pr_body_input, 
                "uc_force_update": uc_force_update # Use local var for force_update flag
            }
            return True, form_data
    return False, None

def render_add_new_file_form(timestamp_str: str):
    """Renders the form for the 'Add New File' action."""
    with st.form(key="add_new_file_form"):
        st.markdown("##### 📄 Specify File Path and Content")
        anf_file_path = st.text_input("File Path to Create", key="anf_file_path_input_widget", placeholder="path/to/your/new_file.txt", help="Full path where the new file will be created (e.g., `src/new_feature.py`). Placeholders can be used.")
        anf_file_content = st.text_area("File Content", key="anf_file_content_area_widget", height=200, help="Content for the new file. Placeholders can be used.")

        st.markdown("---")
        st.markdown("##### 🌳 Branch, Commit, and Pull Request")
        anf_branch_name = st.text_input("New Branch Name", key="anf_branch_name_input_widget", help="Name for the new branch. Placeholders can be used. `{{timestamp}}` is available.")
        anf_commit_message = st.text_input("Commit Message", value="Add {{file_path}}", key="anf_commit_message_input_widget", help="Commit message. `{{file_path}}` (resolved path of the new file) and other placeholders can be used.")
        anf_pr_title = st.text_input("Pull Request Title", value="Add {{file_path}}", key="anf_pr_title_input_widget", help="Title for the Pull Request. Placeholders can be used.")
        anf_pr_body = st.text_area("Pull Request Body", value="This PR adds `{{file_path}}`.", key="anf_pr_body_input_widget", help="Body for the Pull Request. Placeholders can be used.")

        submitted = st.form_submit_button("🚀 Execute Add New File Action", use_container_width=True)
        if submitted:
            form_data = {
                "anf_file_path_input": anf_file_path, 
                "anf_file_content_area": anf_file_content,
                "anf_branch_name_input": anf_branch_name,
                "anf_commit_message_input": anf_commit_message,
                "anf_pr_title_input": anf_pr_title,
                "anf_pr_body_input": anf_pr_body
            }
            return True, form_data
    return False, None 