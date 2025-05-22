import streamlit as st
import sys
import os
from dotenv import load_dotenv
from src import github_utils # Import the module
from github import Github # Import Github class for type hinting and instantiation
import logging # Import the logging module
import datetime # Import datetime to define timestamp
from src import action_processing # <-- NEW IMPORT FOR THE ENTIRE MODULE
from src import ui_components # <-- NEW IMPORT
from src.ui_components import NEW_PLACEHOLDER_METHOD_OPTIONS # <-- IMPORT CONSTANT
# If you wanted to explicitly type `repositories` as List[github_utils.Repository]
# you would also import: from typing import List 

# Add project root to sys.path to allow for src.module imports
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# --- Initialize Logger ---
if 'logger' not in st.session_state:
    logger = logging.getLogger(__name__) # Get a logger specific to this module
    logger.setLevel(logging.DEBUG) # Set the logging level (e.g., DEBUG, INFO, WARNING)
    # Add a handler to output logs to console (Streamlit typically shows this in terminal)
    # Check if handlers are already present to avoid duplication during reruns if logger somehow persists outside session_state logic
    if not logger.handlers:
        ch = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)
    st.session_state.logger = logger
    st.session_state.logger.info("Logger initialized and stored in session state.")

# --- Helper function to process placeholders in a string (MOVED FROM HERE) ---

# Helper function to trigger a rerun for dynamic UI updates
def trigger_rerun():
    st.rerun()

load_dotenv() # Load .env file variables at the start of the application

# Define constants for GitHub OAuth that are used in app.py for the authorize_button
# These were previously partly in github_utils or implicit.
APP_REDIRECT_URI = "http://localhost:8501" # Base URI of the Streamlit app
GITHUB_LOGIN_SCOPE = "repo workflow"
MAX_ACTION_LOG_DISPLAY_HEIGHT = 300 # px, for st.text_area in results

st.set_page_config(layout="wide") # Use wide layout

st.title("GitHub Bulk Repository Operations Tool")

# Load Client ID and Client Secret from environment variables
CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")

# Initialize session state for token if not already present
if 'token' not in st.session_state:
    st.session_state.token = None
# Initialize session state for fetched repositories and errors
if 'repositories_data' not in st.session_state:
    st.session_state.repositories_data = None
if 'repositories_error' not in st.session_state:
    st.session_state.repositories_error = None
if 'repo_name_filter' not in st.session_state: # This will be renamed
    st.session_state.repo_name_filter = "" 
if 'repo_search_text' not in st.session_state: # New state for simple text search
    st.session_state.repo_search_text = ""
if 'organization_name' not in st.session_state:  # New session state for organization
    st.session_state.organization_name = ""
if 'selected_repos' not in st.session_state: # New session state for selected repositories
    st.session_state.selected_repos = set()
if 'repo_actions_results' not in st.session_state: # For storing results of actions
    st.session_state.repo_actions_results = []

# Initialize session state for placeholders
if 'placeholders' not in st.session_state:
    st.session_state.placeholders = [] # List of placeholder definition dicts

# Initialize session state for placeholder method selection UI
# These are for the selectbox OUTSIDE the form, controlling which fields appear INSIDE the form.
if 'selected_ph_method_for_ui' not in st.session_state: 
    st.session_state.selected_ph_method_for_ui = NEW_PLACEHOLDER_METHOD_OPTIONS[0] # Imported constant will be used
if 'selected_ph_method_index_for_ui' not in st.session_state: 
    st.session_state.selected_ph_method_index_for_ui = 0

# Initialize session state for editing mode
if 'editing_placeholder_index' not in st.session_state:
    st.session_state.editing_placeholder_index = None # None means not editing, otherwise stores index
if 'placeholder_form_values_loaded_for_edit' not in st.session_state:
    st.session_state.placeholder_form_values_loaded_for_edit = False

# For testing placeholder configuration from within the form
if 'form_placeholder_test_result_content' not in st.session_state:
    st.session_state.form_placeholder_test_result_content = None # Stores (status, message, default_used_flag)

# Check if credentials were loaded
if not CLIENT_ID or not CLIENT_SECRET:
    st.error("GITHUB_CLIENT_ID or GITHUB_CLIENT_SECRET missing. Ensure they are set in the .env file and the .env file is in the root directory.")
    st.stop()

# Create OAuth component
oauth_component = github_utils.create_oauth_component(CLIENT_ID, CLIENT_SECRET)

# --- Login/Logout Logic directly in app.py ---
if not st.session_state.get('token'):
    # User is not logged in, display login button
    if not oauth_component:
        st.error("OAuth component could not be initialized. Check credentials and .env file setup.") 
        st.stop() # Stop execution if OAuth component fails

# Main application layout after login check
if st.session_state.get('token'):
    access_token = st.session_state.token.get("access_token")
    if not access_token:
        st.error("Failed to retrieve access_token from OAuth response. Please try logging in again.")
        if st.button("Attempt Re-Login"): # Simple re-login attempt
            st.session_state.token = None
            st.rerun()
        st.stop()
    
    # --- UI for Login/Logout (Top Right) and Main Content --- 
    # This will be the new structure
    header_cols = st.columns([0.8, 0.2]) # Adjust ratios as needed
    with header_cols[1]: # Right column for logout
        if st.button("Logout", key="logout_button_main", use_container_width=True):
            st.session_state.token = None
            st.session_state.repositories_data = None
            st.session_state.repositories_error = None
            st.session_state.repo_search_text = ""
            st.session_state.organization_name = ""
            st.session_state.selected_repos = set()
            st.session_state.repo_actions_results = []
            st.session_state.placeholders = []
            st.session_state.editing_placeholder_index = None
            st.session_state.placeholder_form_values_loaded_for_edit = False
            st.session_state.form_placeholder_test_result_content = None
            if 'ph_form_name' in st.session_state: del st.session_state.ph_form_name # Example of clearing session state
            # Consider a more comprehensive reset function for session state
            st.rerun()

    # --- Tabs for selecting repositories and defining actions ---
    tab_titles = ["1. Select Repositories", "2. Define & Execute Action"]
    tab1_selection, tab2_action = st.tabs(tab_titles)

    with tab1_selection:
        st.subheader("Filter and Select Repositories")

        # --- Organization and Search Inputs --- 
        org_name_current = st.text_input(
            "GitHub Organization (optional, leave blank for your repositories):",
            value=st.session_state.organization_name,
            key="organization_name_input_tab1"
        )
        if org_name_current != st.session_state.organization_name:
            st.session_state.organization_name = org_name_current
            st.session_state.repositories_data = None # Clear data on org change
            st.session_state.selected_repos = set()
            st.session_state.repo_actions_results = []

        search_text_current = st.text_input(
            "Search repositories by name (leave blank to list all):", 
            value=st.session_state.repo_search_text,
            key="repo_search_text_input_tab1"
        )
        if search_text_current != st.session_state.repo_search_text:
             st.session_state.repo_search_text = search_text_current
             st.session_state.repositories_data = None # Clear data on search text change
             st.session_state.selected_repos = set()
             st.session_state.repo_actions_results = []

        if st.button("Load/Filter Repositories", key="load_filter_button_tab1"):
            with st.spinner("Fetching repositories..."):
                st.session_state.repositories_data, st.session_state.repositories_error = github_utils.fetch_repositories(
                    access_token, 
                    st.session_state.repo_search_text, 
                    st.session_state.organization_name 
                )
                st.session_state.selected_repos = set() # Clear previous selection on new load
                st.session_state.repo_actions_results = []

        if st.session_state.repositories_error:
            st.error(f"Error fetching repositories: {st.session_state.repositories_error}")
        
        if st.session_state.repositories_data is not None:
            if not st.session_state.repositories_data:
                st.info("No repositories found matching your criteria.")
            else:
                # --- Select/Deselect All Checkbox --- 
                # Determine the current state of the select_all checkbox
                all_repo_ids_in_view = {repo.html_url for repo in st.session_state.repositories_data}
                # Check if all repos in view are currently selected
                # Handles the case where repositories_data is empty or selected_repos is empty
                if all_repo_ids_in_view: # Only proceed if there are repos to select/deselect
                    is_all_selected = all_repo_ids_in_view.issubset(st.session_state.selected_repos)
                else:
                    is_all_selected = False # No repos to select, so "Select All" is effectively false or indeterminate

                # Create a container for the "Select All" checkbox and the list to manage layout
                select_all_container = st.container()
                with select_all_container:
                    if all_repo_ids_in_view: # Only show "Select All" if there are repos
                        select_all_value = st.checkbox(
                            "Select/Deselect All Displayed Repositories", 
                            value=is_all_selected, 
                            key="select_all_repos_cb"
                        )
                        # Logic for Select/Deselect All - run if the checkbox state changed
                        # from its last known state (is_all_selected was based on current data)
                        if select_all_value != is_all_selected: 
                            if select_all_value: # If "Select All" was just checked
                                for repo_id in all_repo_ids_in_view:
                                    st.session_state.selected_repos.add(repo_id)
                            else: # If "Select All" was just unchecked
                                for repo_id in all_repo_ids_in_view:
                                    if repo_id in st.session_state.selected_repos:
                                        st.session_state.selected_repos.remove(repo_id)
                            st.rerun() # Rerun to reflect changes in individual checkboxes
                
                st.markdown("---_**Repository List**_---")
                cols_header = st.columns([0.5, 3, 2]) 
                cols_header[0].write("**Select**")
                cols_header[1].write("**Name**")
                cols_header[2].write("**Last Updated**")

                for repo in st.session_state.repositories_data:
                    repo_id = repo.html_url 
                    cols_row = st.columns([0.5, 3, 2]) 
                    selected = cols_row[0].checkbox(
                        f"Select {repo.name}", 
                        value=(repo_id in st.session_state.selected_repos), 
                        key=f"select_repo_{repo_id}",
                        label_visibility="collapsed"
                    )
                    if selected:
                        st.session_state.selected_repos.add(repo_id)
                    elif repo_id in st.session_state.selected_repos:
                        st.session_state.selected_repos.remove(repo_id)

                    cols_row[1].markdown(f"[{repo.name}]({repo.html_url})") # Link to repo
                    cols_row[2].caption(repo.updated_at) 
    
    with tab2_action:
        st.subheader("Define Action for Selected Repositories")
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

        if not st.session_state.selected_repos:
            st.warning("No repositories selected. Please select repositories in '1. Select Repositories' tab first.")
        else:
            selected_repo_infos = []
            if st.session_state.repositories_data:
                for repo_html_url_selected in st.session_state.selected_repos:
                    repo_info_obj = next((r for r in st.session_state.repositories_data if r.html_url == repo_html_url_selected), None)
                    if repo_info_obj:
                        selected_repo_infos.append(repo_info_obj)
            
            if not selected_repo_infos and st.session_state.selected_repos: 
                st.warning("Could not retrieve detailed information for the selected repositories. Please try reloading repositories in Tab 1.")
            
            st.markdown("**Selected Repositories:**")
            selected_repo_names_display = []
            for repo_html_url_disp in sorted(list(st.session_state.selected_repos)):
                repo_name_disp = next((r.name for r in st.session_state.repositories_data if r.html_url == repo_html_url_disp), "N/A")
                selected_repo_names_display.append(f"- **{repo_name_disp}** ({repo_html_url_disp})")
            with st.expander(f"View {len(selected_repo_names_display)} selected repositories", expanded=False):
                st.markdown("\n".join(selected_repo_names_display))
            st.markdown("---")

            # --- Placeholder Definition UI (CALLING NEW COMPONENT) ---
            with st.expander("Define Dynamic Placeholders (Optional)", expanded=True):
                access_token_for_ui = st.session_state.token.get("access_token") if st.session_state.token else None
                if access_token_for_ui:
                    ui_components.render_placeholder_definition_ui(
                        logger=st.session_state.logger, 
                        access_token=access_token_for_ui, 
                        repositories_data=st.session_state.repositories_data, 
                        selected_repos_urls=st.session_state.selected_repos
                    )
                else:
                    st.error("Access token not available. Cannot render placeholder UI.")
            
            # --- Defined Placeholders List (CALLING NEW COMPONENT) ---
            ui_components.render_defined_placeholders_list(
                logger=st.session_state.logger,
                access_token=access_token_for_ui,
                repositories_data=st.session_state.repositories_data,
                selected_repos_urls=st.session_state.selected_repos
            )

            # --- Choose Action and Configure Parameters ---
            st.markdown("### Choose Action and Configure Parameters")
            
            action_type = st.selectbox(
                "Choose Action Type",
                options=["Remove File", "Update/Create File", "Add New File"],
                key="action_type_selector"
            )

            if action_type == "Remove File":
                # Initialize default branch name for Remove File if not already set or empty
                if not st.session_state.get("rf_branch_name_input_widget"):
                    st.session_state.rf_branch_name_input_widget = "remove-file/{{file_path_placeholder}}"
                
                submitted, form_values_remove = ui_components.render_remove_file_form(timestamp)
                if submitted and form_values_remove:
                    st.session_state.logger.info(f"Executing 'Remove File' action with parameters: {form_values_remove}")
                    if not selected_repo_infos and st.session_state.selected_repos:
                        st.error("No valid repository data for selected items. Cannot proceed.")
                    elif not st.session_state.selected_repos:
                         st.warning("No repositories selected to perform action on.")
                    else:
                        with st.spinner(f"Executing 'Remove File' action for {len(selected_repo_infos)} repositories..."):
                            g_instance = Github(access_token) 
                            results = action_processing.execute_remove_file_action(
                                g=g_instance,
                                selected_repo_infos=selected_repo_infos,
                                defined_placeholders=st.session_state.get("placeholders", []),
                                action_config_from_form=form_values_remove, 
                                logger=st.session_state.logger
                            )
                            st.session_state.repo_actions_results = results
                            st.rerun()

            elif action_type == "Update/Create File":
                # Initialize default branch name for Update/Create File if not already set or empty
                if not st.session_state.get("uf_branch_name_input"):
                    st.session_state.uf_branch_name_input = f"update-file-{timestamp}"

                submitted, form_values_update = ui_components.render_update_file_form(timestamp)
                if submitted and form_values_update:
                    st.session_state.logger.info(f"Executing 'Update/Create File' action with parameters: {form_values_update}")
                    if not selected_repo_infos and st.session_state.selected_repos:
                        st.error("No valid repository data for selected items. Cannot proceed.")
                    elif not st.session_state.selected_repos:
                         st.warning("No repositories selected to perform action on.")
                    else:
                        with st.spinner(f"Executing 'Update/Create File' action for {len(selected_repo_infos)} repositories..."):
                            g_instance = Github(access_token)
                            results = action_processing.execute_update_file_action(
                                g=g_instance,
                                selected_repo_infos=selected_repo_infos,
                                defined_placeholders=st.session_state.get("placeholders", []),
                                action_config_from_form=form_values_update,
                                logger=st.session_state.logger
                            )
                            st.session_state.repo_actions_results = results
                        st.rerun()

            elif action_type == "Add New File":
                # Initialize default branch name for Add New File if not already set or empty
                if not st.session_state.get("anf_branch_name_input_widget"):
                    st.session_state.anf_branch_name_input_widget = f"add-file-{timestamp}"

                submitted, form_values_add = ui_components.render_add_new_file_form(timestamp)
                if submitted and form_values_add:
                    st.session_state.logger.info(f"Executing 'Add New File' action with parameters: {form_values_add}")
                    if not selected_repo_infos and st.session_state.selected_repos:
                        st.error("No valid repository data for selected items. Cannot proceed.")
                    elif not st.session_state.selected_repos:
                         st.warning("No repositories selected to perform action on.")
                    else:
                        with st.spinner(f"Executing 'Add New File' action for {len(selected_repo_infos)} repositories..."):
                            g_instance = Github(access_token)
                            results = action_processing.execute_add_new_file_action(
                                g=g_instance,
                                selected_repo_infos=selected_repo_infos,
                                defined_placeholders=st.session_state.get("placeholders", []),
                                action_config_from_form=form_values_add, 
                                logger=st.session_state.logger
                            )
                            st.session_state.repo_actions_results = results
                        st.rerun()
            
            st.markdown("---")

        # Global display for action results, outside any specific action tab form
        if st.session_state.repo_actions_results:
            st.markdown("---")
            st.subheader("Last Action Results")
            for result in st.session_state.repo_actions_results:
                # Make repo name bold in results
                repo_display_name = result.get('repo', 'Unknown repo')
                if result.get("success"):
                    with st.expander(f"SUCCESS: {repo_display_name}", expanded=False):
                        st.text(result['message'])
                        if "pr_url" in result and result["pr_url"]:
                            st.markdown(f"  **Pull Request:** [{result['pr_url']}]({result['pr_url']})")
                else:
                    with st.expander(f"FAILURE: {repo_display_name}", expanded=True):
                        st.text(result['message'])

else:  # User is not logged in
    st.info("Please log in with GitHub to use the tool.")
    if oauth_component:
        login_cols = st.columns([0.3, 0.4, 0.3]) # Adjust for desired centering
        with login_cols[1]:
            result = oauth_component.authorize_button(
                name="Login with GitHub",
                redirect_uri=APP_REDIRECT_URI,
                scope=GITHUB_LOGIN_SCOPE,
                icon="https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png",
                use_container_width=True,
                key="main_login_button" 
            )
            if result and 'token' in result:
                st.session_state.token = result.get('token')
                st.session_state.repositories_data = None 
                st.session_state.repositories_error = None
                st.session_state.repo_search_text = "" 
                st.session_state.organization_name = ""
                st.session_state.selected_repos = set()
                st.session_state.repo_actions_results = []
                st.session_state.placeholders = []
                st.session_state.editing_placeholder_index = None
                st.session_state.placeholder_form_values_loaded_for_edit = False
                st.session_state.form_placeholder_test_result_content = None
                st.rerun()
            elif result and 'error' in result:
                st.error(f"Authorization error: {result.get('error', 'Unknown error')}. Details: {result.get('error_description', 'N/A')}")
    else:
        st.error("OAuth component is not available. Please check application configuration.") 