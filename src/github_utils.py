from streamlit_oauth import OAuth2Component
import github # Import the main github module
from dataclasses import dataclass, field
import fnmatch # Added for filename pattern matching
import re # Ensure re is imported for re.sub
import base64
import logging
import json # Added for JSON parsing
import yaml # Added for YAML parsing
from github.Repository import Repository as PyGithubRepository # Alias for PyGithub Repository
from typing import List, Optional, Any, Tuple, Dict # Added Tuple, Dict
from jsonpath_ng import jsonpath, parse

print(f"[DEBUG] github_utils.py (global scope): type(github.ContentFile.ContentFile) after import = {type(github.ContentFile.ContentFile)}") # Check type of class via module path

# GitHub OAuth Endpoints and Scopes (still needed for OAuth2Component)
_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_TOKEN_URL = "https://github.com/login/oauth/access_token"
_SCOPE = "repo workflow"

@dataclass
class Repository:
    """Dataclass to hold GitHub repository information."""
    name: str
    full_name: str
    html_url: str
    updated_at: str
    default_branch: str
    description: Optional[str] = None
    private: Optional[bool] = None
    fork: Optional[bool] = None
    archived: Optional[bool] = None
    created_at: Optional[str] = None
    pushed_at: Optional[str] = None
    owner_login: Optional[str] = None

# --- New Dataclasses for structured results ---
@dataclass
class FileContentResult:
    content: Optional[str] = None
    sha: Optional[str] = None
    default_branch_name: Optional[str] = None
    error: Optional[str] = None

@dataclass
class BranchOperationResult:
    success: bool
    message: Optional[str] = None
    branch_object: Optional[github.Branch.Branch] = None # PyGithub's Branch object

@dataclass
class PullRequestResult:
    html_url: Optional[str] = None
    message: Optional[str] = None

@dataclass
class FileOperationStatus: # For operations like delete
    success: bool
    message: Optional[str] = None

@dataclass
class FileUpdateResult: # For update, includes new_sha
    success: bool
    message: Optional[str] = None
    new_sha: Optional[str] = None

@dataclass
class TargetFilesResult:
    files: List[github.ContentFile.ContentFile] = field(default_factory=list) # PyGithub's ContentFile
    error: Optional[str] = None

@dataclass
class PlaceholderExtractionResult:
    value: Optional[str] = None
    error: Optional[str] = None
# --- End of New Dataclasses ---

def create_oauth_component(client_id: str = None, client_secret: str = None) -> Optional[Any]:
    """
    Creates and returns an OAuth2Component instance.
    Returns None if client_id or client_secret is missing.
    """
    if not client_id or not client_secret:
        return None
    return OAuth2Component(client_id, client_secret, _AUTHORIZE_URL, _TOKEN_URL)

def fetch_repositories(access_token: str, search_query: Optional[str] = None, org_name: Optional[str] = None, logger: Optional[logging.Logger] = None) -> tuple[Optional[List[Repository]], Optional[str]]:
    g = github.Github(access_token)
    if logger is None: # Fallback logger if none provided
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.WARNING) # Be less verbose by default for this util
        if not logger.handlers:
            ch = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - github_utils - %(levelname)s - %(message)s')
            ch.setFormatter(formatter)
            logger.addHandler(ch)
            
    try:
        user = g.get_user() 
        query_parts = []
        if search_query:
            query_parts.append(f"{search_query.strip()} in:name")

        owner_filter_part = f"user:{user.login}" # Default to current user
        if org_name and org_name.strip():
            owner_filter_part = f"org:{org_name.strip()}"
        query_parts.append(owner_filter_part)
        
        final_query = " ".join(query_parts)
        logger.info(f"Searching GitHub repositories with query: '{final_query}'")
        
        # Use get_repos() if there is no text search_query, otherwise search_repositories
        # This is more efficient for simply listing all user/organization repositories
        fetched_repos_raw = []
        if org_name and org_name.strip():
            owner = g.get_organization(org_name.strip())
            fetched_repos_raw = owner.get_repos(sort="updated", direction="desc")
        else:
            # For users, get the authenticated user first, then their repos with affiliation
            authenticated_user = g.get_user()
            fetched_repos_raw = authenticated_user.get_repos(affiliation='owner', sort="updated", direction="desc") 

        # Filter by name if search_query is provided
        # Because get_repos() does not allow full-text search in the name like search_repositories()
        if search_query and search_query.strip():
            filtered_repos_after_fetch = []
            search_lower = search_query.strip().lower()
            for repo_raw in fetched_repos_raw:
                if search_lower in repo_raw.name.lower():
                    filtered_repos_after_fetch.append(repo_raw)
            pygithub_repos = filtered_repos_after_fetch
        else:
            pygithub_repos = list(fetched_repos_raw) # Convert to list if it's not a PaginatedList

        repositories_data: List[Repository] = []
        for item in pygithub_repos: # item is of type PyGithubRepository
            try:
                default_branch_name = item.default_branch
            except github.GithubException as e_branch:
                logger.warning(f"Could not determine default branch for {item.full_name}: {e_branch}. Skipping repo.")
                default_branch_name = "main" # Fallback, although we should ideally skip

            repo_owner_login = item.owner.login if item.owner else "N/A"

            repositories_data.append(
                Repository(
                    name=item.name,
                    full_name=item.full_name,
                    html_url=item.html_url,
                    updated_at=item.updated_at.strftime('%Y-%m-%d %H:%M:%S') if item.updated_at else "N/A",
                    default_branch=default_branch_name,
                    description=item.description if item.description else "", # Ensure description is not None
                    private=bool(item.private),
                    fork=bool(item.fork),
                    archived=bool(item.archived),
                    created_at=item.created_at.strftime('%Y-%m-%d %H:%M:%S') if item.created_at else "N/A",
                    pushed_at=item.pushed_at.strftime('%Y-%m-%d %H:%M:%S') if item.pushed_at else "N/A",
                    owner_login=repo_owner_login
                )
            )
        logger.info(f"Fetched {len(repositories_data)} repositories.")
        return repositories_data, None
    except github.GithubException as e:
        logger.error(f"GitHub API error while fetching repositories: {e.status} {e.data}", exc_info=True)
        return None, f"GitHub API Error: {e.data.get('message', str(e)) if isinstance(e.data, dict) else str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error fetching repositories: {e}", exc_info=True)
        return None, f"An unexpected error occurred: {str(e)}"

def get_file_content(g: github.Github, repo_full_name: str, file_path: str, branch: str | None = None) -> FileContentResult:
    """
    Fetches the content and SHA of a file from a GitHub repository.
    Also attempts to determine and return the default branch if no specific branch is provided.

    Args:
        g: Initialized PyGithub instance.
        repo_full_name: The full name of the repository (e.g., 'owner/repo').
        file_path: The path to the file within the repository.
        branch: The specific branch to fetch the file from. If None, uses the repo's default branch.

    Returns:
        A FileContentResult object.
    """
    try:
        repo = g.get_repo(repo_full_name)
        
        actual_branch = branch
        default_branch_name = repo.default_branch # Store default branch name

        if actual_branch is None:
            actual_branch = default_branch_name
            if actual_branch is None: # Should ideally not happen if repo object is valid
                return FileContentResult(error=f"Could not determine default branch for {repo_full_name}.")

        try:
            content_file_or_list = repo.get_contents(file_path, ref=actual_branch)

            # First, check if the path resulted in a list of items (i.e., it was a directory)
            if isinstance(content_file_or_list, list):
                return FileContentResult(default_branch_name=default_branch_name, error=f"Path '{file_path}' is a directory, not a file. Please provide a path to a specific file.")
            
            # If it's not a list, it should be a ContentFile object (or similar individual item)
            # Now check its type attribute, as before
            content_file = content_file_or_list # Rename for clarity in the rest of the block
            if hasattr(content_file, 'type') and content_file.type == "dir": 
                return FileContentResult(default_branch_name=default_branch_name, error=f"Path '{file_path}' is a directory, not a file.")
            
            # Ensure content is decoded if it's base64 encoded
            if not hasattr(content_file, 'decoded_content'):
                 return FileContentResult(default_branch_name=default_branch_name, error=f"The item at '{file_path}' does not have decodable content (it might be a submodule or an unexpected type).")

            file_content = content_file.decoded_content.decode("utf-8") 
            return FileContentResult(content=file_content, sha=content_file.sha, default_branch_name=default_branch_name)
        except github.UnknownObjectException:
            # File not found in the specified branch
            return FileContentResult(default_branch_name=default_branch_name, error=f"File '{file_path}' not found in branch '{actual_branch}' of {repo_full_name}.")
        except github.GithubException as e:
            # Other GitHub related errors (e.g., permissions, API issues for get_contents)
            return FileContentResult(default_branch_name=default_branch_name, error=f"GitHub API error getting file '{file_path}' from '{actual_branch}': {e.data.get('message', str(e))}")

    except github.UnknownObjectException:
        return FileContentResult(error=f"Repository '{repo_full_name}' not found.")
    except github.GithubException as e:
        return FileContentResult(error=f"GitHub API error getting repo '{repo_full_name}': {e.data.get('message', str(e))}")
    except Exception as e:
        # Catch-all for other unexpected errors
        return FileContentResult(error=f"An unexpected error occurred while fetching file: {e}") 

def create_branch(g: github.Github, repo_full_name: str, new_branch_name: str, source_branch_name: str) -> BranchOperationResult:
    """
    Creates a new branch in the specified repository from a source branch.
    If the branch already exists, it uses the existing branch.

    Args:
        g: Initialized PyGithub instance.
        repo_full_name: The full name of the repository (e.g., 'owner/repo').
        new_branch_name: The name for the new branch.
        source_branch_name: The name of the branch from which to create the new one.

    Returns:
        A BranchOperationResult object.
    """
    repo = None # Initialize repo to None for broader scope in error messages if g.get_repo fails
    new_branch_name_for_log = new_branch_name if new_branch_name else "[BRANCH_NAME_MISSING]"
    source_branch_name_for_log = source_branch_name if source_branch_name else "[SOURCE_BRANCH_NAME_MISSING]"

    try:
        repo = g.get_repo(repo_full_name)
        existing_branch_obj: github.Branch.Branch | None = None
        branch_already_existed = False

        try:
            existing_branch_obj = repo.get_branch(new_branch_name_for_log)
            branch_already_existed = True
            print(f"[DEBUG] Branch '{new_branch_name_for_log}' found by get_branch(). Will use this existing branch.")
        except github.UnknownObjectException:
            print(f"[DEBUG] Branch '{new_branch_name_for_log}' was not found by get_branch() (UnknownObjectException). Will proceed to attempt creation from '{source_branch_name_for_log}'.")
            pass # Branch does not exist, normal creation path will follow
        except github.GithubException as e_get_existing_branch:
            if e_get_existing_branch.status == 404:
                print(f"[DEBUG] Branch '{new_branch_name_for_log}' was not found by get_branch() (GithubException Status 404). Will proceed to attempt creation from '{source_branch_name_for_log}'.")
                pass # Treat 404 as branch not existing
            else:
                print(f"[ERROR] Unexpected GithubException (type: {type(e_get_existing_branch)}) when checking if branch '{new_branch_name_for_log}' exists: {e_get_existing_branch.data.get('message', str(e_get_existing_branch))} (Status: {e_get_existing_branch.status})")
                return BranchOperationResult(success=False, message=f"Error checking for existing branch '{new_branch_name_for_log}'.")
        except Exception as e_get_existing_branch_generic:
            print(f"[ERROR] Generic Exception (type: {type(e_get_existing_branch_generic)}) when checking if branch '{new_branch_name_for_log}' exists: {str(e_get_existing_branch_generic)}")
            return BranchOperationResult(success=False, message=f"Unexpected error checking for existing branch '{new_branch_name_for_log}'.")

        if branch_already_existed and existing_branch_obj:
             # If branch already existed and we successfully got its object, we can return early.
             return BranchOperationResult(success=True, message=f"Using existing branch '{new_branch_name_for_log}'.", branch_object=existing_branch_obj)

        # If branch_already_existed is False, or if existing_branch_obj is somehow None (should not happen if True),
        # proceed to creation logic.
        print(f"[DEBUG] Proceeding to fetch source branch '{source_branch_name_for_log}' for creating '{new_branch_name_for_log}'.")
        
        source_branch_sha = None
        try:
            print(f"[DEBUG] Attempting to get source branch: '{source_branch_name_for_log}' in repo '{repo_full_name}'.")
            source_branch = repo.get_branch(source_branch_name_for_log)
            source_branch_sha = source_branch.commit.sha
            print(f"[DEBUG] Successfully fetched source branch '{source_branch_name_for_log}'. SHA: {source_branch_sha}")
        except github.UnknownObjectException as guoe_source:
            print(f"[ERROR] Source branch '{source_branch_name_for_log}' not found (github.UnknownObjectException). Details: {guoe_source.data.get('message', str(guoe_source))}")
            return BranchOperationResult(success=False, message=f"Source branch '{source_branch_name_for_log}' not found in '{repo_full_name}'.")
        except github.GithubException as ge_source_branch:
            print(f"[ERROR] GitHub API error (github.GithubException) when trying to get source branch '{source_branch_name_for_log}': {ge_source_branch.data.get('message', str(ge_source_branch))} (Status: {ge_source_branch.status})")
            return BranchOperationResult(success=False, message=f"GitHub API error getting source branch '{source_branch_name_for_log}'.")
        except Exception as e_source_branch_generic:
            print(f"[ERROR] Unexpected generic Exception (type: {type(e_source_branch_generic)}) when trying to get source branch '{source_branch_name_for_log}': {str(e_source_branch_generic)}")
            return BranchOperationResult(success=False, message=f"Unexpected error getting source branch '{source_branch_name_for_log}'.")

        if not source_branch_sha:
             print(f"[ERROR] Failed to obtain SHA for source branch '{source_branch_name_for_log}' in '{repo_full_name}'. source_branch_sha is None or empty. Cannot create ref.")
             return BranchOperationResult(success=False, message=f"Failed to obtain SHA for source branch '{source_branch_name_for_log}'.")

        print(f"[DEBUG CREATE_GIT_REF] Attempting to create git ref. Path: 'refs/heads/{new_branch_name_for_log}', SHA: '{source_branch_sha}'.")
        created_ref = None
        try:
            created_ref = repo.create_git_ref(
                ref=f"refs/heads/{new_branch_name_for_log}", 
                sha=source_branch_sha
            )
            print(f"[DEBUG CREATE_GIT_REF] Successfully called repo.create_git_ref for 'refs/heads/{new_branch_name_for_log}'. Ref object: {created_ref}")
        except github.GithubException as e_create_ref:
            # Specifically check for "Reference already exists" (status 422)
            if e_create_ref.status == 422 and "Reference already exists" in e_create_ref.data.get("message", ""):
                print(f"[DEBUG CREATE_GIT_REF] repo.create_git_ref failed because reference 'refs/heads/{new_branch_name_for_log}' already exists (API error 422). This confirms the branch exists.")
                # Try to get the branch object again, as the initial check might have issues or race conditions
                try:
                    final_branch_obj = repo.get_branch(new_branch_name_for_log)
                    print(f"[DEBUG] Successfully fetched branch '{new_branch_name_for_log}' after 422 error on create_git_ref.")
                    return BranchOperationResult(success=True, message=f"Using existing branch '{new_branch_name_for_log}' (confirmed by create_git_ref failure).", branch_object=final_branch_obj)
                except Exception as e_get_branch_after_422:
                    print(f"[ERROR] Failed to get branch '{new_branch_name_for_log}' even after create_git_ref indicated it exists. Error: {str(e_get_branch_after_422)}")
                    return BranchOperationResult(success=False, message=f"Branch '{new_branch_name_for_log}' seems to exist but could not be fetched after create_git_ref reported it exists.")
            else:
                print(f"[ERROR CREATE_GIT_REF] Caught github.GithubException during repo.create_git_ref. Path: 'refs/heads/{new_branch_name_for_log}', SHA: '{source_branch_sha}'. Error: {e_create_ref.data.get('message', str(e_create_ref))} (Status: {e_create_ref.status})")
                # Re-raise to be caught by the main GithubException handler if not the 422 "already exists" error.
                raise e_create_ref 
        except Exception as e_create_ref_generic: 
            print(f"[ERROR CREATE_GIT_REF] Caught generic Exception (type: {type(e_create_ref_generic)}) during repo.create_git_ref. Path: 'refs/heads/{new_branch_name_for_log}', SHA: '{source_branch_sha}'. Error: {str(e_create_ref_generic)}.")
            raise e_create_ref_generic 
            
        # If create_git_ref was successful
        print(f"[DEBUG] Branch '{new_branch_name_for_log}' ref created successfully via create_git_ref.")
        return BranchOperationResult(success=True, message=f"Branch '{new_branch_name_for_log}' created successfully.", branch_object=None)
        
    except github.UnknownObjectException as guoe_outer:
        repo_name_for_log = repo.full_name if repo else repo_full_name # Use repo.full_name if available
        print(f"[ERROR] Outer github.UnknownObjectException caught. Repo: '{repo_name_for_log}'. Message: {guoe_outer.data.get('message', str(guoe_outer))}")
        # This might be repo not found if g.get_repo() fails, or other rare UnknownObject scenarios.
        if "Repository not found" in guoe_outer.data.get('message', "") or not repo: # Check if it was repo not found
            return BranchOperationResult(success=False, message=f"Repository '{repo_full_name}' not found.")
        return BranchOperationResult(success=False, message=f"Unexpected UnknownObjectException for '{repo_name_for_log}'. Details: {guoe_outer.data.get('message', str(guoe_outer))}")

    except github.GithubException as ge_outer:
        repo_name_for_log = repo.full_name if repo else repo_full_name
        print(f"[ERROR] Outer github.GithubException caught. Repo: '{repo_name_for_log}'. Error: {ge_outer.data.get('message', str(ge_outer))} (Status: {ge_outer.status}). Attempted ref: 'refs/heads/{new_branch_name_for_log}'")
        return BranchOperationResult(success=False, message=f"GitHub API error during branch operation for '{new_branch_name_for_log}' in '{repo_name_for_log}'. Details: {ge_outer.data.get('message', str(ge_outer))}")
    except Exception as e_outer_generic:
        repo_name_for_log = repo.full_name if repo else repo_full_name
        print(f"[ERROR] Outer generic Exception (type: {type(e_outer_generic)}) caught in create_branch for '{new_branch_name_for_log}' in '{repo_name_for_log}': {str(e_outer_generic)}")
        return BranchOperationResult(success=False, message=f"An unexpected error occurred while operating on branch '{new_branch_name_for_log}' in '{repo_name_for_log}'.")

def delete_file(g: github.Github, repo_full_name: str, file_path: str, commit_message: str, branch_name: str, sha: str) -> FileOperationStatus:
    """
    Deletes a file in the specified repository and branch.

    Args:
        g: Initialized PyGithub instance.
        repo_full_name: The full name of the repository (e.g., 'owner/repo').
        file_path: The path to the file to be deleted.
        commit_message: The commit message for the deletion.
        branch_name: The name of the branch where the file will be deleted.
        sha: The blob SHA of the file to be deleted.

    Returns:
        A FileOperationStatus object.
    """
    try:
        repo = g.get_repo(repo_full_name)
        # PyGithub's delete_file method takes path, message, sha, and branch
        repo.delete_file(
            path=file_path,
            message=commit_message,
            sha=sha,
            branch=branch_name
        )
        return FileOperationStatus(success=True)
    except github.UnknownObjectException as e:
        # This could mean the repo, branch, or file (identified by SHA for deletion) was not found.
        # Or the path does not exist for deletion.
        # For deletion, if the SHA is from a file that no longer exists at that path, or branch is wrong,
        # it can also lead to an error.
        return FileOperationStatus(success=False, message=f"Error deleting file '{file_path}' in '{repo_full_name}' on branch '{branch_name}'. Resource not found or SHA mismatch. Details: {e.data.get('message', str(e))}")
    except github.GithubException as e:
        # Handle other GitHub API errors, e.g., permissions, or if the file has changed (SHA mismatch not caught as UnknownObjectException)
        return FileOperationStatus(success=False, message=f"GitHub API error deleting file '{file_path}' in '{repo_full_name}': {e.data.get('message', str(e))} (Status: {e.status})")
    except Exception as e:
        return FileOperationStatus(success=False, message=f"An unexpected error occurred while deleting file '{file_path}': {e}") 

def create_pull_request(g: github.Github, repo_full_name: str, head_branch: str, base_branch: str, title: str, body: str) -> PullRequestResult:
    """
    Creates a pull request in the specified repository.
    If an open pull request already exists for the head_branch and base_branch,
    its URL is returned with an appropriate message.

    Args:
        g: Initialized PyGithub instance.
        repo_full_name: The full name of the repository (e.g., 'owner/repo').
        head_branch: The name of the branch where your changes are implemented.
        base_branch: The name of the branch you want the changes pulled into.
        title: The title of the pull request.
        body: The body/description of the pull request.

    Returns:
        A PullRequestResult object.
    """
    try:
        repo = g.get_repo(repo_full_name)
        owner_login = repo.owner.login # Get owner login for precise head filter

        # Check for existing pull requests
        existing_pulls = repo.get_pulls(
            state='open', 
            head=f'{owner_login}:{head_branch}',  # More specific: 'owner:branch'
            base=base_branch
        )
        
        count = 0
        existing_pr_html_url = None
        for pr_item in existing_pulls: # PaginatedList, usually 0 or 1 for specific head/base
            existing_pr_html_url = pr_item.html_url
            count += 1
            if count > 0: # Found at least one
                break 
        
        if existing_pr_html_url:
            return PullRequestResult(html_url=existing_pr_html_url, message=f"Pull Request already exists for branch '{head_branch}' targeting '{base_branch}'.")

        # If no existing PR, create a new one
        pr = repo.create_pull(
            title=title,
            body=body,
            head=head_branch,
            base=base_branch
        )
        return PullRequestResult(html_url=pr.html_url) # Success, new PR created

    except github.GithubException as e:
        error_detail = e.data.get('message', str(e))
        if e.data.get('errors'):
            error_messages = [err.get('message', '') for err in e.data.get('errors', [])]
            error_detail = "; ".join(filter(None, error_messages)) if error_messages else error_detail
        
        # Specific check for "No commits between X and Y" which is a valid scenario, not an error for this logic
        # but still means PR cannot be created.
        if "No commits between" in error_detail and "and" in error_detail:
             return PullRequestResult(message=f"No new commits in '{head_branch}' to create a Pull Request against '{base_branch}'. {error_detail}")

        # Check for "A pull request already exists" error
        if "A pull request already exists" in error_detail:
            # Try to find the existing PR again
            try:
                existing_pulls = repo.get_pulls(
                    state='open', 
                    head=f'{owner_login}:{head_branch}',
                    base=base_branch
                )
                for pr_item in existing_pulls:
                    return PullRequestResult(html_url=pr_item.html_url, message=f"Pull Request already exists for branch '{head_branch}' targeting '{base_branch}'.")
            except Exception as e2:
                # If we can't find the PR, return the original error
                return PullRequestResult(message=f"GitHub API error creating pull request in '{repo_full_name}' (head: '{head_branch}', base: '{base_branch}'): {error_detail} (Status: {e.status})")

        return PullRequestResult(message=f"GitHub API error creating pull request in '{repo_full_name}' (head: '{head_branch}', base: '{base_branch}'): {error_detail} (Status: {e.status})")
    except Exception as e:
        return PullRequestResult(message=f"An unexpected error occurred while creating pull request in '{repo_full_name}': {e}")

def update_file(
    repo: github.Repository.Repository, 
    file_path: str, 
    new_content_str: str, # This will be the primary content for "Replace entire content" or the new content after search/replace
    commit_message: str, 
    branch_name: str, 
    current_sha_from_app: str | None, # SHA provided by app if known (e.g. for retry)
    logger: logging.Logger,
    # New parameters for search and replace functionality
    update_mode: str = "Replace entire content", # Default to existing behavior
    search_string: str | None = None,
    replace_with_string: str | None = None,
    is_regex: bool = False,
    replace_all: bool = True,
    default_branch_for_sr_fallback: str | None = None, # New parameter for default branch
    force_update: bool = False # ADDED: New parameter for forcing update on conflict
) -> FileUpdateResult:
    """
    Updates an existing file or creates a new one in the repository.
    Supports replacing entire content or searching and replacing within the content.

    Args:
        repo: PyGithub Repository object.
        file_path: Path to the file.
        new_content_str: The new content for the file if mode is 'Replace entire content'.
                         If mode is 'Search and replace', this argument is initially ignored
                         and the content to be written is derived from search/replace logic.
        commit_message: Commit message.
        branch_name: Branch to commit to.
        current_sha_from_app: Known SHA of the file, if available (e.g., for retrying an update).
                              If None, the function will try to fetch the current SHA.
        logger: Logger instance.
        update_mode: "Replace entire content" or "Search and replace string".
        search_string: String to search for (if mode is 'Search and replace string').
        replace_with_string: String to replace with (if mode is 'Search and replace string').
        is_regex: Whether search_string is a regex (if mode is 'Search and replace string').
        replace_all: Whether to replace all occurrences (if mode is 'Search and replace string').
        default_branch_for_sr_fallback: The default branch of the repo, to fetch original content for Search/Replace if not on working branch.
        force_update: If True and a 409 conflict occurs in 'Search and replace string' mode, 
                      attempt to delete and then re-create the file.

    Returns:
        A FileUpdateResult object.
    """
    logger.info(f"Attempting to update/create file: '{file_path}' in branch '{branch_name}' of repo '{repo.full_name}'. Mode: '{update_mode}'")
    
    # --- MODIFIED: Always determine current SHA and existence on the target branch_name first ---
    actual_existing_file_sha_on_branch = None
    file_exists_on_branch = False
    try:
        file_on_branch_obj = repo.get_contents(file_path, ref=branch_name)
        if isinstance(file_on_branch_obj, list):
            logger.error(f"Path '{file_path}' on target branch '{branch_name}' is a directory.")
            return FileUpdateResult(success=False, message=f"Path '{file_path}' on target branch '{branch_name}' is a directory.")
        if hasattr(file_on_branch_obj, 'sha') and hasattr(file_on_branch_obj, 'decoded_content'):
            actual_existing_file_sha_on_branch = file_on_branch_obj.sha
            file_exists_on_branch = True
            logger.info(f"File '{file_path}' exists on target branch '{branch_name}'. SHA: {actual_existing_file_sha_on_branch}.")
        else:
             logger.warning(f"Could not reliably determine SHA or content for '{file_path}' on target branch '{branch_name}'. Assuming it might not exist or is not a file.")
    except github.UnknownObjectException:
        logger.info(f"File '{file_path}' not found on target branch '{branch_name}'. Will proceed as a create operation on this branch if content is provided.")
    except github.GithubException as e_get_content_target:
        logger.error(f"GithubException when trying to get_contents for '{file_path}' on target branch '{branch_name}': {e_get_content_target.data.get('message', str(e_get_content_target))}")
        return FileUpdateResult(success=False, message=f"Error checking file '{file_path}' on target branch '{branch_name}': {e_get_content_target.data.get('message', str(e_get_content_target))}")
    except Exception as e_generic_get_content_target:
        logger.error(f"Generic exception when trying to get_contents for '{file_path}' on target branch '{branch_name}': {str(e_generic_get_content_target)}", exc_info=True)
        return FileUpdateResult(success=False, message=f"Unexpected error checking file '{file_path}' on target branch '{branch_name}': {str(e_generic_get_content_target)}")
    # --- END MODIFIED SECTION ---

    content_to_write_str = "" 
    # existing_file_sha = current_sha_from_app # This is now superseded by actual_existing_file_sha_on_branch
    # file_exists = False # This is now superseded by file_exists_on_branch
    
    # 1. Determine current SHA and if file exists (unless SHA already provided) - THIS BLOCK IS NOW LARGELY REDUNDANT
    # The logic above (MODIFIED SECTION) has already determined actual_existing_file_sha_on_branch and file_exists_on_branch
    # We will use these definitive values. current_sha_from_app is now only a hint, if needed at all.

    # if not existing_file_sha: # This was based on current_sha_from_app
    #     try:
    #         # Try to get the file to see if it exists and get its SHA
    #         file_content_obj = repo.get_contents(file_path, ref=branch_name)
    #         if isinstance(file_content_obj, list): # Should not happen if file_path is a file
    #              logger.error(f"Path '{file_path}' resolved to a directory, not a file, during update_file content check.")
    #              return FileUpdateResult(success=False, message=f"Path '{file_path}' is a directory, not a file.")
    #         if hasattr(file_content_obj, 'sha') and hasattr(file_content_obj, 'decoded_content'):
    #             existing_file_sha = file_content_obj.sha
    #             file_exists = True
    #             logger.info(f"File '{file_path}' exists. SHA: {existing_file_sha}.")
    #         else: 
    #             logger.warning(f"Could not reliably determine SHA or content for '{file_path}'. Assuming it might not exist or is not a file.")
    #             file_exists = False 
    #     except github.UnknownObjectException:
    #         logger.info(f"File '{file_path}' not found in branch '{branch_name}'. Will attempt to create it.")
    #         existing_file_sha = None 
    #         file_exists = False
    #     # ... (rest of the original try-except for getting content) ...

    # 2. Prepare content_to_write_str based on update_mode
    if update_mode == "Search and replace string":
        if search_string is None or replace_with_string is None:
            logger.error("Search/Replace mode selected, but search_string or replace_with_string is None.")
            return FileUpdateResult(success=False, message="Search string and replace string must be provided for 'Search and replace string' mode.")

        current_content_str = ""
        content_source_info_for_log = f"target branch '{branch_name}'"
        content_fetched_for_sr = False

        if file_exists_on_branch: # File was found on the target branch by the initial check
            try:
                # Fetch content from the target branch
                file_obj_for_sr = repo.get_contents(file_path, ref=branch_name)
                if isinstance(file_obj_for_sr, list): # Defensive check
                    logger.error(f"Path '{file_path}' on {content_source_info_for_log} is a directory (SR content fetch).")
                    return FileUpdateResult(success=False, message=f"Path '{file_path}' on {content_source_info_for_log} is a directory.")
                if hasattr(file_obj_for_sr, 'decoded_content'):
                    current_content_str = file_obj_for_sr.decoded_content.decode('utf-8')
                    content_fetched_for_sr = True
                    logger.info(f"Fetched content of '{file_path}' from {content_source_info_for_log} for search/replace.")
                else:
                    logger.error(f"Could not decode content from '{file_path}' on {content_source_info_for_log} for search/replace.")
                    return FileUpdateResult(success=False, message=f"Could not decode content from '{file_path}' on {content_source_info_for_log}.")
            except github.UnknownObjectException: # Should not happen if file_exists_on_branch is true
                logger.error(f"File '{file_path}' was initially found on {content_source_info_for_log} but disappeared. This is unexpected.")
                return FileUpdateResult(success=False, message=f"File '{file_path}' disappeared from {content_source_info_for_log}.")
            except Exception as e_get_content_working_branch:
                logger.error(f"Error getting content of '{file_path}' from {content_source_info_for_log}: {e_get_content_working_branch}", exc_info=True)
                return FileUpdateResult(success=False, message=f"Error reading file '{file_path}' from {content_source_info_for_log}.")
        
        # Fallback to default_branch_for_sr_fallback if content wasn't fetched from target branch
        # AND default_branch_for_sr_fallback is provided
        if not content_fetched_for_sr and default_branch_for_sr_fallback:
            logger.info(f"Content for '{file_path}' not obtained from target branch '{branch_name}'. For Search/Replace, attempting to fetch from default branch '{default_branch_for_sr_fallback}'.")
            try:
                file_obj_from_default = repo.get_contents(file_path, ref=default_branch_for_sr_fallback)
                content_source_info_for_log = f"default branch '{default_branch_for_sr_fallback}'"
                if isinstance(file_obj_from_default, list): # Defensive check
                    logger.error(f"Path '{file_path}' on {content_source_info_for_log} is a directory (SR fallback).")
                    return FileUpdateResult(success=False, message=f"Path '{file_path}' on {content_source_info_for_log} is a directory.")
                if hasattr(file_obj_from_default, 'decoded_content'):
                    current_content_str = file_obj_from_default.decoded_content.decode('utf-8')
                    content_fetched_for_sr = True 
                    logger.info(f"Fetched content of '{file_path}' for search/replace from {content_source_info_for_log}.")
                    # If content comes from fallback, and file didn't exist on target branch, it's a creation.
                    # actual_existing_file_sha_on_branch would be None in this case.
                else:
                    logger.warning(f"Could not decode content from '{file_path}' on {content_source_info_for_log} (fallback). Search/Replace may operate on empty string if file is truly empty there.")
            except github.UnknownObjectException:
                logger.warning(f"File '{file_path}' also not found on default branch '{default_branch_for_sr_fallback}' (fallback).")
            except Exception as e_get_default_content:
                logger.error(f"Error getting content of '{file_path}' from default branch '{default_branch_for_sr_fallback}' (fallback): {e_get_default_content}", exc_info=True)

        if not content_fetched_for_sr: # If still no content after trying target and fallback
            logger.warning(f"File '{file_path}' does not exist or content is inaccessible for Search/Replace (after trying target and fallback). Skipping S/R operation for this file.")
            # If the original intention was to create the file if not found, this S/R part will skip, 
            # and later logic (create_file) might still run if new_content_str is non-empty from "Replace entire content" mode
            # but for S/R, if no content, no S/R.
            # We need to decide if this is a failure for the S/R mode or if it should proceed to create empty if file_path was specified.
            # For now, treat as an error for S/R if no source content.
            return FileUpdateResult(success=False, message=f"File '{file_path}' not found or content inaccessible for Search/Replace.")

        logger.info(f"Proceeding with Search/Replace for '{file_path}'. Content for SR obtained from: {content_source_info_for_log}. Length: {len(current_content_str)}")
        try:
            if is_regex:
                num_replacements = 0 if replace_all else 1
                content_to_write_str = re.sub(search_string, replace_with_string, current_content_str, count=num_replacements)
            else:
                if replace_all:
                    content_to_write_str = current_content_str.replace(search_string, replace_with_string)
                else:
                    content_to_write_str = current_content_str.replace(search_string, replace_with_string, 1)
            logger.info(f"Performed search/replace on '{file_path}'.")
        except re.error as e_regex:
            logger.error(f"Regex error during search/replace for '{file_path}': {e_regex}")
            return FileUpdateResult(success=False, message=f"Invalid regular expression: {e_regex}")
        except Exception as e_replace:
            logger.error(f"Error during string replacement for '{file_path}': {e_replace}", exc_info=True)
            return FileUpdateResult(success=False, message=f"Error during string replacement: {e_replace}")
    
    elif update_mode == "Replace entire content":
        content_to_write_str = new_content_str 
        logger.info(f"Mode is 'Replace entire content' for '{file_path}'.")
    else:
        logger.error(f"Unknown update_mode: '{update_mode}' for file '{file_path}'.")
        return FileUpdateResult(success=False, message=f"Invalid update mode: {update_mode}")

    # 3. Perform the update or create operation using actual_existing_file_sha_on_branch
    try:
        if actual_existing_file_sha_on_branch: # Indicates file exists on target branch, so update it
            logger.info(f"Updating existing file '{file_path}' (SHA: {actual_existing_file_sha_on_branch}) in branch '{branch_name}'.")
            update_result_payload = repo.update_file(
                path=file_path, 
                message=commit_message, 
                content=content_to_write_str.encode('utf-8'), 
                sha=actual_existing_file_sha_on_branch, 
                branch=branch_name
            )
            new_file_sha = update_result_payload['content'].sha
            logger.info(f"File '{file_path}' updated successfully. New SHA: {new_file_sha}")
            return FileUpdateResult(success=True, message=f"File '{file_path}' updated successfully.", new_sha=new_file_sha)
        else: # File doesn't exist on target branch, create it
            logger.info(f"Creating new file '{file_path}' in branch '{branch_name}'.")
            create_result = repo.create_file(
                path=file_path, 
                message=commit_message, 
                content=content_to_write_str.encode('utf-8'), 
                branch=branch_name
            )
            new_file_sha = create_result['content'].sha
            logger.info(f"File '{file_path}' created successfully. New SHA: {new_file_sha}")
            return FileUpdateResult(success=True, message=f"File '{file_path}' created successfully.", new_sha=new_file_sha)
            
    except github.GithubException as e:
        error_msg = e.data.get('message', str(e))
        logger.error(f"GitHub API error during file operation on '{file_path}': {error_msg} (Status: {e.status})")
        
        if e.status == 409 and force_update and update_mode == "Search and replace string":
            logger.warning(f"Conflict (409) updating '{file_path}'. Force update is enabled. Attempting delete then create.")
            try:
                # For force update, we need the SHA of the file *as it currently is on the branch* to delete it
                # This was already fetched as actual_existing_file_sha_on_branch if file_exists_on_branch was true.
                # If it wasn't found (actual_existing_file_sha_on_branch is None), but we got a 409, something is fishy.
                # However, a 409 typically implies the SHA we *tried* to update with was stale.
                # The SHA needed for delete_file is the *current* blob SHA.
                
                sha_for_delete_attempt = actual_existing_file_sha_on_branch # Default to what we found
                
                if not sha_for_delete_attempt: # If we didn't find it on the branch initially, but got 409, try re-fetching
                    logger.info(f"Force Update: SHA on branch was initially None, but got 409. Re-fetching SHA of '{file_path}' for deletion.")
                    refetched_file_info = repo.get_contents(file_path, ref=branch_name) # This might fail if file truly vanished
                    if isinstance(refetched_file_info, github.ContentFile.ContentFile) and hasattr(refetched_file_info, 'sha'):
                        sha_for_delete_attempt = refetched_file_info.sha
                        logger.info(f"Force Update: Re-fetched SHA for delete: {sha_for_delete_attempt}")
                    else:
                        err_delete_sha = f"Force Update: Could not re-fetch current SHA of '{file_path}' for deletion after 409. Aborting force update."
                        logger.error(err_delete_sha)
                        return FileUpdateResult(success=False, message=f"Conflict on '{file_path}'. Force update failed: {err_delete_sha}")
                
                if not sha_for_delete_attempt: # Still no SHA for delete after re-fetch attempt
                     err_delete_sha = f"Force Update: SHA for deletion of '{file_path}' is still None after 409. Cannot proceed with delete. Aborting."
                     logger.error(err_delete_sha)
                     return FileUpdateResult(success=False, message=f"Conflict on '{file_path}'. Force update failed: {err_delete_sha}")

                logger.info(f"Force Update: Deleting '{file_path}' (SHA: {sha_for_delete_attempt}) with commit: 'Forcing update: Deleting before recreate'")
                repo.delete_file(
                    path=file_path, 
                    message=f"Forcing update: Deleting '{file_path}' before recreate", 
                    sha=sha_for_delete_attempt, 
                    branch=branch_name
                )
                logger.info(f"Force Update: File '{file_path}' deleted. Now attempting to create it with new content.")
                
                create_after_delete_result = repo.create_file(
                    path=file_path, 
                    message=commit_message, 
                    content=content_to_write_str.encode('utf-8'), 
                    branch=branch_name
                )
                new_forced_sha = create_after_delete_result['content'].sha
                logger.info(f"Force Update: File '{file_path}' created successfully after delete. New SHA: {new_forced_sha}")
                return FileUpdateResult(success=True, message=f"File '{file_path}' force updated (deleted and recreated).", new_sha=new_forced_sha)

            except github.GithubException as e_force:
                force_error_msg = e_force.data.get('message', str(e_force))
                logger.error(f"Force Update: GitHubException during delete/create for '{file_path}': {force_error_msg} (Status: {e_force.status})")
                return FileUpdateResult(success=False, message=f"Conflict on '{file_path}'. Force update attempt failed: {force_error_msg}")
            except Exception as e_force_generic:
                logger.error(f"Force Update: Unexpected error during delete/create for '{file_path}': {e_force_generic}", exc_info=True)
                return FileUpdateResult(success=False, message=f"Conflict on '{file_path}'. Force update attempt failed with unexpected error: {e_force_generic}")
        
        return FileUpdateResult(success=False, message=f"GitHub API error for '{file_path}' (Status: {e.status}): {error_msg}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during file operation on '{file_path}': {e}", exc_info=True)
        return FileUpdateResult(success=False, message=f"Unexpected error with file '{file_path}': {e}")

def find_target_files(
    g: github.Github,
    repo_full_name: str,
    target_branch: str,
    target_path_input: str | None = None, # Can be file, dir, or None
    filename_filter_input: str | None = None,
    content_query_input: str | None = None
) -> TargetFilesResult:
    """
    Identifies target files in a repository based on a combination of path, filename filter, and content query.

    Args:
        g: Initialized PyGithub instance.
        repo_full_name: The full name of the repository (e.g., 'owner/repo').
        target_branch: The specific branch to operate on.
        target_path_input: Optional. Path to a specific file, a directory, or None (search entire repo).
        filename_filter_input: Optional. Glob-like pattern for filenames (e.g., '*.txt').
        content_query_input: Optional. Text string to search for in file content.

    Returns:
        A TargetFilesResult object.
    """
    found_files_list: list[github.ContentFile.ContentFile] = [] # Renamed to avoid conflict with dataclass field

    try:
        repo = g.get_repo(repo_full_name)
    except github.UnknownObjectException:
        return TargetFilesResult(error=f"Repository '{repo_full_name}' not found.")
    except github.GithubException as e:
        return TargetFilesResult(error=f"GitHub API error getting repo '{repo_full_name}': {e.data.get('message', str(e))}")
    except Exception as e:
        return TargetFilesResult(error=f"Unexpected error getting repo '{repo_full_name}': {e}")

    # Scenario A: target_path_input might be a direct path to a file.
    if target_path_input and not target_path_input.endswith('/'): # Heuristic: if no trailing slash, could be a file
        try:
            # Try to get it as a single file/content object
            content_item = repo.get_contents(target_path_input, ref=target_branch)
            print(f"[DEBUG] github_utils.find_target_files: Scenario A - type(content_item): {type(content_item)}, type(github.ContentFile.ContentFile): {type(github.ContentFile.ContentFile)}, type(list): {type(list)}") # DEBUG
            
            if isinstance(content_item, github.ContentFile.ContentFile): # It's a single file
                if content_query_input:
                    # Verify content if query is provided
                    file_content_res = get_file_content(g, repo_full_name, content_item.path, target_branch)
                    if file_content_res.error:
                        return TargetFilesResult(error=f"Error reading content of alleged file '{content_item.path}': {file_content_res.error}")
                    if file_content_res.content is None or content_query_input not in file_content_res.content:
                        return TargetFilesResult() # File found, but content query doesn't match
                # If no content query, or if query matches, this is our target file.
                return TargetFilesResult(files=[content_item])
            elif isinstance(content_item, list): # It's a directory, proceed to Scenario B logic
                # This means target_path_input was actually a dir path without a trailing slash.
                # The logic below for directories will handle this.
                pass # Fall through to directory logic

        except github.UnknownObjectException:
            # target_path_input does not exist as specified (could be dir or non-existent file)
            # Fall through to general search logic, which might catch it if it's part of a broader pattern search
            # or if it was intended as a directory that needs content/filename search.
            # If it was an exact file path that was not found, and no other criteria match, it will result in empty list.
            pass # Continue to Scenario B logic, maybe it was a dir path without slash
        except github.GithubException as e:
            return TargetFilesResult(error=f"GitHub API error checking path '{target_path_input}': {e.data.get('message', str(e))}")

    # Scenario B: target_path_input is a directory (or None for repo root), or was a file but now handled by content search.
    # Effective path for searching (directory or root)
    search_dir = target_path_input.strip('/') if target_path_input else ""

    if content_query_input: # Search by content (primary mechanism: search_code)
        query_parts = [content_query_input, f"repo:{repo_full_name}"]
        if search_dir:
            query_parts.append(f"path:{search_dir}")
        if filename_filter_input:
            query_parts.append(f"filename:{filename_filter_input}")
        
        final_query = " ".join(query_parts)
        print(f"[DEBUG] github_utils.find_target_files (search_code): final_query = {final_query}") # Debug print

        try:
            results = g.search_code(query=final_query) 
            count = 0
            for item in results:
                if count >= 100: break # Limit results
                # Ensure item is a ContentFile, not a stub from search results that lacks details
                # It's generally better to re-fetch with get_contents to ensure branch accuracy and full object
                try:
                    detailed_content_file = repo.get_contents(item.path, ref=target_branch)
                    if isinstance(detailed_content_file, github.ContentFile.ContentFile):
                        found_files_list.append(detailed_content_file)
                    count +=1
                except github.UnknownObjectException:
                    pass # File from search result not found in target_branch, skip
                except github.GithubException:
                    pass # Error fetching details for specific file, skip
            return TargetFilesResult(files=found_files_list)
        except github.GithubException as e:
            err_msg_detail = e.data.get('message', str(e))
            if 'errors' in e.data and e.data['errors']:
                 err_msg_detail = "; ".join([err.get('message','') for err in e.data['errors']])
            return TargetFilesResult(error=f"GitHub API error (search_code): {err_msg_detail} (Query: {final_query})")
        except Exception as e:
            return TargetFilesResult(error=f"Unexpected error (search_code): {e} (Query: {final_query})")

    elif filename_filter_input: # No content query, but filename filter exists. Use git tree.
        try:
            branch_obj = repo.get_branch(target_branch) # Get branch object
            branch_commit_sha = branch_obj.commit.sha  # Get SHA of the branch's latest commit
            
            git_tree = repo.get_git_tree(sha=branch_commit_sha, recursive=True) # Use sha instead of ref
            if not git_tree or not git_tree.tree:
                return TargetFilesResult(error="Could not retrieve file tree for the repository/branch.")
            
            for element in git_tree.tree:
                if element.type == 'blob': # It's a file
                    # Check if file is within the search_dir (if search_dir is specified)
                    if search_dir and not element.path.startswith(search_dir.strip('/') + '/'):
                        if search_dir.strip('/') != element.path: # allow exact match if search_dir is a file path itself
                             if not (search_dir == "" and '/' not in element.path): # allow root files if search_dir is empty
                                continue

                    if fnmatch.fnmatch(element.path.split('/')[-1], filename_filter_input): # Match filename part
                        try:
                            # Fetch the full ContentFile object as tree elements are lightweight
                            content_file_obj = repo.get_contents(element.path, ref=target_branch)
                            print(f"[DEBUG] github_utils.find_target_files: Scenario B (tree) - type(content_file_obj): {type(content_file_obj)}, type(github.ContentFile.ContentFile): {type(github.ContentFile.ContentFile)}") # DEBUG
                            if isinstance(content_file_obj, github.ContentFile.ContentFile):
                                found_files_list.append(content_file_obj)
                            if len(found_files_list) >= 200: break # Safety limit for tree walk results
                        except github.UnknownObjectException: 
                            pass # File in tree no longer accessible, skip
                        except github.GithubException:
                            pass # Error fetching specific file, skip
            return TargetFilesResult(files=found_files_list)
        except github.GithubException as e:
            return TargetFilesResult(error=f"GitHub API error getting git tree: {e.data.get('message', str(e))}")
        except Exception as e:
            return TargetFilesResult(error=f"Unexpected error getting git tree: {e}")
    else:
        # No content_query and no filename_filter. 
        # If target_path_input was a dir, this state means insufficient criteria.
        # If target_path_input was a specific file handled above, this won't be reached.
        # This case should ideally be caught by app.py validation.
        return TargetFilesResult(error="Insufficient criteria: Please specify a filename filter or content to search, or an exact file path.")

# Helper function to navigate a dictionary using a dot-separated path
def _get_value_from_path(data: dict, path: str, logger: logging.Logger) -> tuple[any, str | None]:
    try:
        keys = path.split('.')
        value = data
        for key in keys:
            if isinstance(value, dict):
                if key in value:
                    value = value[key]
                else:
                    # Try to match case-insensitively as a fallback for common YAML/JSON usage
                    found_key = None
                    for k_actual in value.keys():
                        # Ensure k_actual is a string before calling .lower()
                        if isinstance(k_actual, str) and k_actual.lower() == key.lower():
                            value = value[k_actual]
                            found_key = k_actual
                            break
                    if not found_key:
                        logger.warning(f"Key '{key}' not found in path '{path}'. Available keys: {list(value.keys())}")
                        return None, f"Key '{key}' not found in path '{path}'"
            elif isinstance(value, list): # Basic support for list index
                try:
                    idx = int(key)
                    if 0 <= idx < len(value):
                        value = value[idx]
                    else:
                        logger.warning(f"Index {idx} out of bounds for key '{key}' in path '{path}'")
                        return None, f"Index {idx} out of bounds for key '{key}' in path '{path}'"
                except ValueError:
                    logger.warning(f"Invalid index '{key}' in path '{path}'. Expected an integer.")
                    return None, f"Invalid index '{key}' in path '{path}'"
            else:
                logger.warning(f"Cannot navigate further at '{key}' in path '{path}'. Value is not a dict or list.")
                return None, f"Cannot navigate further at '{key}' in path '{path}'. Value is not a dict or list."
        return value, None
    except Exception as e:
        logger.error(f"Error navigating path '{path}': {e}")
        return None, f"Error navigating path '{path}': {e}"

def extract_placeholder_value(
    g: github.Github, 
    repo_full_name: str, 
    branch: str, 
    file_path: str, 
    extraction_method: str, 
    extraction_config: dict, 
    logger: logging.Logger
) -> PlaceholderExtractionResult:
    """
    Extracts a value from a specified file in a GitHub repository using a defined method.

    Args:
        g: Initialized PyGithub instance.
        repo_full_name: Full name of the repository (e.g., 'owner/repo').
        branch: Branch to read the file from.
        file_path: Path to the file in the repository.
        extraction_method: The method to use for extraction ("Regex", "JSON Path", "YAML Path").
        extraction_config: Configuration dictionary for the chosen method.
        logger: Logger instance for logging messages.

    Returns:
        A PlaceholderExtractionResult object.
    """
    logger.info(f"[{repo_full_name}] Attempting to extract placeholder value from '{file_path}' on branch '{branch}' using method '{extraction_method}'.")
    
    file_content_result = get_file_content(g, repo_full_name, file_path, branch)

    if file_content_result.error:
        logger.warning(f"[{repo_full_name}] Failed to get file '{file_path}': {file_content_result.error}")
        return PlaceholderExtractionResult(error=f"Failed to get file '{file_path}': {file_content_result.error}")

    if file_content_result.content is None: # Should be caught by error_get_file, but as a safeguard
        logger.warning(f"[{repo_full_name}] File '{file_path}' content is None.")
        # This can be a valid state if get_file_content returns content=None without error (e.g. empty file)
        # However, most extraction methods will fail on None content.
        # Let's pass this through and let specific extraction logic handle it or fail.
        # If an extraction method *can* work with None content (unlikely), it will.
        # If not, it should produce its own error.
        # For consistency, we can return an error here as it's unlikely extraction will succeed.
        return PlaceholderExtractionResult(error=f"File '{file_path}' content is None (or could not be decoded).")


    file_content_str = file_content_result.content # Now we know content is not None
    extracted_value: any = None
    error_during_extraction_logic: str | None = None # Specific error from the extraction block

    try:
        if extraction_method == "Regex":
            pattern = extraction_config.get("pattern")
            group_index = extraction_config.get("group_index", 0)
            if not pattern:
                error_during_extraction_logic = "Regex pattern not provided in config."
            else:
                match = re.search(pattern, file_content_str)
                if match:
                    if group_index < 0 or group_index > len(match.groups()):
                         error_during_extraction_logic = f"Regex group_index {group_index} is out of bounds."
                         logger.warning(f"[{repo_full_name}] {error_during_extraction_logic}")
                    else:
                        extracted_value = match.group(group_index)
                        logger.info(f"[{repo_full_name}] Regex matched. Group {group_index} value: '{extracted_value}'")
                else:
                    error_during_extraction_logic = f"Regex pattern '{pattern}' did not match in file '{file_path}'."
                    logger.info(f"[{repo_full_name}] {error_during_extraction_logic}")

        elif extraction_method == "JSON Path":
            jsonpath_expression = extraction_config.get("jsonpath_expression")
            if not jsonpath_expression:
                error_during_extraction_logic = "JSONPath expression not provided in config."
            else:
                try:
                    data = json.loads(file_content_str)
                    extracted_value, error_during_extraction_logic = _get_value_from_path(data, jsonpath_expression, logger)
                    if not error_during_extraction_logic and extracted_value is not None:
                        logger.info(f"[{repo_full_name}] JSONPath '{jsonpath_expression}' evaluated to: '{extracted_value}'")
                    elif not error_during_extraction_logic and extracted_value is None:
                        logger.info(f"[{repo_full_name}] JSONPath '{jsonpath_expression}' found, but value is null.")
                    elif error_during_extraction_logic:
                        logger.warning(f"[{repo_full_name}] JSONPath error: {error_during_extraction_logic}")

                except json.JSONDecodeError as e_json:
                    error_during_extraction_logic = f"Failed to parse JSON from '{file_path}': {e_json}"
                    logger.warning(f"[{repo_full_name}] {error_during_extraction_logic}")
        
        elif extraction_method == "YAML Path":
            yaml_path_config = extraction_config.get("yaml_path")
            list_of_yaml_paths = []

            if isinstance(yaml_path_config, str): # Backward compatibility: treat single string as a list with one item
                if yaml_path_config.strip():
                    list_of_yaml_paths = [yaml_path_config.strip()]
            elif isinstance(yaml_path_config, list):
                list_of_yaml_paths = [p for p in yaml_path_config if isinstance(p, str) and p.strip()] # Ensure all items are strings and not empty

            if not list_of_yaml_paths:
                error_during_extraction_logic = "YAML Path list not provided or is empty in config."
                logger.warning(f"[{repo_full_name}] {error_during_extraction_logic}")
            else:
                try:
                    data = yaml.safe_load(file_content_str)
                    if not isinstance(data, (dict, list)): # _get_value_from_path expects dict or list as root
                        error_during_extraction_logic = f"YAML content in '{file_path}' is not a valid mapping or sequence (e.g. JSON object or array)."
                        logger.warning(f"[{repo_full_name}] {error_during_extraction_logic}")
                    else:
                        path_specific_errors = []
                        for path_expression in list_of_yaml_paths:
                            logger.info(f"[{repo_full_name}] Trying YAML Path: '{path_expression}'")
                            current_value, path_err = _get_value_from_path(data, path_expression, logger)
                            if path_err:
                                path_specific_errors.append(f"Path '{path_expression}': {path_err}")
                            
                            if current_value is not None and not path_err: # Successfully extracted a non-None value
                                extracted_value = current_value
                                error_during_extraction_logic = None # Clear any previous path errors as we found a value
                                logger.info(f"[{repo_full_name}] YAML Path '{path_expression}' successful. Value: '{extracted_value}'")
                                break # Found a value, stop trying other paths
                            elif current_value is None and not path_err: # Path valid, but value is explicitly null/None
                                # This is a valid extraction of None. We should continue if other paths might yield non-None.
                                # If this is the *only* path or the *last* successful (null) path, `extracted_value` will remain None.
                                logger.info(f"[{repo_full_name}] YAML Path '{path_expression}' resolved to null/None.")
                                # If by the end, extracted_value is still None (from the last successful null or no successes),
                                # the logic after the loop will handle it. We don't set error_during_extraction_logic here
                                # unless all paths fail with errors.
                        
                        if extracted_value is None and path_specific_errors and len(path_specific_errors) == len(list_of_yaml_paths):
                            # All paths resulted in errors
                            error_during_extraction_logic = f"All YAML paths failed. Errors: [{'; '.join(path_specific_errors)}]"
                            logger.warning(f"[{repo_full_name}] {error_during_extraction_logic}")
                        elif extracted_value is None and not error_during_extraction_logic: 
                            # No path error, but no non-None value found (all paths might have led to None or were skipped)
                            # or some paths errored but at least one resolved to None without error.
                            error_during_extraction_logic = f"None of the provided YAML paths yielded a non-null value from '{file_path}'. Tried: {list_of_yaml_paths}"
                            logger.info(f"[{repo_full_name}] {error_during_extraction_logic}")


                except yaml.YAMLError as e_yaml:
                    error_during_extraction_logic = f"Failed to parse YAML from '{file_path}': {e_yaml}"
                    logger.warning(f"[{repo_full_name}] {error_during_extraction_logic}")
        else:
            error_during_extraction_logic = f"Unsupported extraction method: '{extraction_method}'."
            logger.error(f"[{repo_full_name}] {error_during_extraction_logic}")

    except Exception as e_general:
        error_during_extraction_logic = f"Unexpected error during value extraction: {e_general}"
        logger.error(f"[{repo_full_name}] {error_during_extraction_logic}", exc_info=True)

    if error_during_extraction_logic:
        return PlaceholderExtractionResult(error=error_during_extraction_logic)
    
    # If successfully extracted (no error_during_extraction_logic)
    if extracted_value is None: # Successfully extracted a null/None value, or no value found from multiple paths
        logger.info(f"[{repo_full_name}] Extraction for method '{extraction_method}' in file '{file_path}' resulted in a None value (or no path yielded a value). Returning None value without error message for this part.")
        # This means the extraction process itself was successful, but the found value is None.
        # We return value=None and error=None (as the extraction logic didn't error out).
        return PlaceholderExtractionResult(value=None, error=None)

    return PlaceholderExtractionResult(value=str(extracted_value), error=None) 