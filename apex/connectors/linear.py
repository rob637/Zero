"""
Linear Connector - Linear.app Integration

Issue tracking and project management via Linear's GraphQL API.

Setup:
    1. Go to Linear Settings > API > Personal API keys
    2. Create a key with appropriate scopes
    
    export LINEAR_API_KEY="your-api-key"

    from connectors.linear import LinearConnector
    linear = LinearConnector(api_key="your-key")
"""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://api.linear.app/graphql"


class LinearConnector:
    """Linear issue tracking via GraphQL API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("LINEAR_API_KEY", "")
        self.connected = bool(self.api_key)

    async def connect(self) -> bool:
        """Validate Linear API credentials."""
        self.connected = bool(self.api_key)
        return self.connected

    async def _graphql(self, query: str, variables: Optional[Dict] = None) -> Dict:
        """Execute a GraphQL query."""
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                GRAPHQL_URL,
                headers={
                    "Authorization": self.api_key,
                    "Content-Type": "application/json",
                },
                json={"query": query, "variables": variables or {}},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("errors"):
                raise RuntimeError(data["errors"][0].get("message", "GraphQL error"))
            return data.get("data", {})

    # ── Issues ──

    async def list_issues(
        self,
        team_key: Optional[str] = None,
        status: Optional[str] = None,
        assignee: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict]:
        """List issues with optional filters.
        
        Args:
            team_key: Team key to filter by (e.g. "ENG")
            status: Status name to filter (e.g. "In Progress", "Done", "Todo")
            assignee: Assignee name or "me" for current user
            limit: Max results (default 20)
        """
        filters = []
        if team_key:
            filters.append(f'team: {{ key: {{ eq: "{team_key}" }} }}')
        if status:
            filters.append(f'state: {{ name: {{ eq: "{status}" }} }}')
        if assignee:
            if assignee.lower() == "me":
                filters.append('assignee: { isMe: { eq: true } }')
            else:
                filters.append(f'assignee: {{ name: {{ containsIgnoreCase: "{assignee}" }} }}')

        filter_str = ", ".join(filters)
        filter_clause = f", filter: {{ {filter_str} }}" if filter_str else ""

        query = f"""
        query {{
            issues(first: {limit}{filter_clause}, orderBy: updatedAt) {{
                nodes {{
                    id identifier title description priority priorityLabel
                    state {{ name color }}
                    assignee {{ name email }}
                    team {{ name key }}
                    labels {{ nodes {{ name color }} }}
                    createdAt updatedAt
                    dueDate estimate url
                }}
            }}
        }}"""
        
        data = await self._graphql(query)
        return [self._parse_issue(n) for n in data.get("issues", {}).get("nodes", [])]

    async def get_issue(self, issue_id: str) -> Dict:
        """Get a single issue by ID or identifier (e.g. "ENG-123").
        
        Args:
            issue_id: Issue UUID or identifier like "ENG-123"
        """
        # Try by identifier first (common usage)
        query = """
        query($id: String!) {
            issueSearch(query: $id, first: 1) {
                nodes {
                    id identifier title description priority priorityLabel
                    state { name color }
                    assignee { name email }
                    team { name key }
                    labels { nodes { name color } }
                    comments { nodes { body user { name } createdAt } }
                    createdAt updatedAt
                    dueDate estimate url
                }
            }
        }"""
        
        data = await self._graphql(query, {"id": issue_id})
        nodes = data.get("issueSearch", {}).get("nodes", [])
        if not nodes:
            raise ValueError(f"Issue not found: {issue_id}")
        
        result = self._parse_issue(nodes[0])
        # Include comments for single issue view
        comments = nodes[0].get("comments", {}).get("nodes", [])
        result["comments"] = [{
            "body": c.get("body", ""),
            "author": c.get("user", {}).get("name", ""),
            "created_at": c.get("createdAt", ""),
        } for c in comments]
        return result

    async def create_issue(
        self,
        title: str,
        team_key: str,
        description: Optional[str] = None,
        priority: Optional[int] = None,
        assignee_id: Optional[str] = None,
        status: Optional[str] = None,
        labels: Optional[List[str]] = None,
        due_date: Optional[str] = None,
        estimate: Optional[int] = None,
    ) -> Dict:
        """Create a new issue.
        
        Args:
            title: Issue title
            team_key: Team key (e.g. "ENG"). Use list_teams to find available teams.
            description: Issue description (supports markdown)
            priority: 0=No priority, 1=Urgent, 2=High, 3=Medium, 4=Low
            assignee_id: User ID to assign to
            status: Status name (e.g. "Todo", "In Progress")  
            labels: List of label names
            due_date: Due date (YYYY-MM-DD)
            estimate: Story points estimate
        """
        # First get team ID
        team_data = await self._graphql(
            'query($key: String!) { teams(filter: { key: { eq: $key } }) { nodes { id } } }',
            {"key": team_key},
        )
        teams = team_data.get("teams", {}).get("nodes", [])
        if not teams:
            raise ValueError(f"Team not found: {team_key}")
        
        input_data: Dict[str, Any] = {
            "title": title,
            "teamId": teams[0]["id"],
        }
        if description:
            input_data["description"] = description
        if priority is not None:
            input_data["priority"] = priority
        if assignee_id:
            input_data["assigneeId"] = assignee_id
        if due_date:
            input_data["dueDate"] = due_date
        if estimate is not None:
            input_data["estimate"] = estimate

        # Handle status by name
        if status:
            state_data = await self._graphql(
                """query($teamId: String!, $name: String!) {
                    workflowStates(filter: { team: { id: { eq: $teamId } }, name: { eq: $name } }) {
                        nodes { id }
                    }
                }""",
                {"teamId": teams[0]["id"], "name": status},
            )
            states = state_data.get("workflowStates", {}).get("nodes", [])
            if states:
                input_data["stateId"] = states[0]["id"]

        # Handle labels by name
        if labels:
            label_data = await self._graphql(
                """query($teamId: String!) {
                    issueLabels(filter: { team: { id: { eq: $teamId } } }) {
                        nodes { id name }
                    }
                }""",
                {"teamId": teams[0]["id"]},
            )
            all_labels = {l["name"].lower(): l["id"] for l in label_data.get("issueLabels", {}).get("nodes", [])}
            label_ids = [all_labels[l.lower()] for l in labels if l.lower() in all_labels]
            if label_ids:
                input_data["labelIds"] = label_ids

        query = """
        mutation($input: IssueCreateInput!) {
            issueCreate(input: $input) {
                success
                issue {
                    id identifier title
                    state { name }
                    assignee { name }
                    team { key }
                    url
                }
            }
        }"""
        
        data = await self._graphql(query, {"input": input_data})
        result = data.get("issueCreate", {})
        if not result.get("success"):
            raise RuntimeError("Failed to create issue")
        return self._parse_issue(result.get("issue", {}))

    async def update_issue(
        self,
        issue_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[int] = None,
        assignee_id: Optional[str] = None,
        due_date: Optional[str] = None,
        estimate: Optional[int] = None,
    ) -> Dict:
        """Update an issue.
        
        Args:
            issue_id: Issue UUID
            title: New title
            description: New description
            status: New status name
            priority: New priority (0-4)
            assignee_id: New assignee ID
            due_date: New due date (YYYY-MM-DD)
            estimate: New estimate
        """
        input_data: Dict[str, Any] = {}
        if title:
            input_data["title"] = title
        if description:
            input_data["description"] = description
        if priority is not None:
            input_data["priority"] = priority
        if assignee_id:
            input_data["assigneeId"] = assignee_id
        if due_date:
            input_data["dueDate"] = due_date
        if estimate is not None:
            input_data["estimate"] = estimate

        # Handle status by name
        if status:
            # Get the issue's team first
            issue_data = await self._graphql(
                'query($id: String!) { issue(id: $id) { team { id } } }',
                {"id": issue_id},
            )
            team_id = issue_data.get("issue", {}).get("team", {}).get("id")
            if team_id:
                state_data = await self._graphql(
                    """query($teamId: String!, $name: String!) {
                        workflowStates(filter: { team: { id: { eq: $teamId } }, name: { eq: $name } }) {
                            nodes { id }
                        }
                    }""",
                    {"teamId": team_id, "name": status},
                )
                states = state_data.get("workflowStates", {}).get("nodes", [])
                if states:
                    input_data["stateId"] = states[0]["id"]

        query = """
        mutation($id: String!, $input: IssueUpdateInput!) {
            issueUpdate(id: $id, input: $input) {
                success
                issue {
                    id identifier title
                    state { name }
                    assignee { name }
                    url
                }
            }
        }"""
        
        data = await self._graphql(query, {"id": issue_id, "input": input_data})
        result = data.get("issueUpdate", {})
        if not result.get("success"):
            raise RuntimeError("Failed to update issue")
        return self._parse_issue(result.get("issue", {}))

    async def add_comment(self, issue_id: str, body: str) -> Dict:
        """Add a comment to an issue.
        
        Args:
            issue_id: Issue UUID
            body: Comment text (supports markdown)
        """
        query = """
        mutation($input: CommentCreateInput!) {
            commentCreate(input: $input) {
                success
                comment { id body createdAt user { name } }
            }
        }"""
        
        data = await self._graphql(query, {"input": {"issueId": issue_id, "body": body}})
        result = data.get("commentCreate", {})
        if not result.get("success"):
            raise RuntimeError("Failed to add comment")
        comment = result.get("comment", {})
        return {
            "id": comment.get("id", ""),
            "body": comment.get("body", ""),
            "author": comment.get("user", {}).get("name", ""),
            "created_at": comment.get("createdAt", ""),
        }

    async def search_issues(self, query: str, limit: int = 20) -> List[Dict]:
        """Full-text search across all issues.
        
        Args:
            query: Search text
            limit: Max results (default 20)
        """
        gql = """
        query($query: String!, $first: Int!) {
            issueSearch(query: $query, first: $first) {
                nodes {
                    id identifier title description priority priorityLabel
                    state { name color }
                    assignee { name email }
                    team { name key }
                    labels { nodes { name color } }
                    createdAt updatedAt url
                }
            }
        }"""
        
        data = await self._graphql(gql, {"query": query, "first": limit})
        return [self._parse_issue(n) for n in data.get("issueSearch", {}).get("nodes", [])]

    # ── Teams ──

    async def list_teams(self) -> List[Dict]:
        """List all teams in the workspace."""
        query = """
        query {
            teams {
                nodes {
                    id name key description
                    members { nodes { name email } }
                    states { nodes { name color type } }
                    labels { nodes { name color } }
                }
            }
        }"""
        
        data = await self._graphql(query)
        teams = []
        for t in data.get("teams", {}).get("nodes", []):
            teams.append({
                "id": t.get("id", ""),
                "name": t.get("name", ""),
                "key": t.get("key", ""),
                "description": t.get("description", ""),
                "members": [{"name": m.get("name", ""), "email": m.get("email", "")}
                           for m in t.get("members", {}).get("nodes", [])],
                "statuses": [{"name": s.get("name", ""), "type": s.get("type", "")}
                            for s in t.get("states", {}).get("nodes", [])],
                "labels": [l.get("name", "") for l in t.get("labels", {}).get("nodes", [])],
            })
        return teams

    # ── Cycles (Sprints) ──

    async def list_cycles(self, team_key: Optional[str] = None, limit: int = 5) -> List[Dict]:
        """List cycles (sprints).
        
        Args:
            team_key: Filter by team key
            limit: Max results (default 5)
        """
        filter_str = ""
        if team_key:
            filter_str = f', filter: {{ team: {{ key: {{ eq: "{team_key}" }} }} }}'

        query = f"""
        query {{
            cycles(first: {limit}, orderBy: updatedAt{filter_str}) {{
                nodes {{
                    id number name
                    startsAt endsAt completedAt
                    progress
                    team {{ name key }}
                    issues {{ nodes {{ id identifier title state {{ name }} }} }}
                }}
            }}
        }}"""
        
        data = await self._graphql(query)
        cycles = []
        for c in data.get("cycles", {}).get("nodes", []):
            cycles.append({
                "id": c.get("id", ""),
                "number": c.get("number"),
                "name": c.get("name", ""),
                "starts_at": c.get("startsAt", ""),
                "ends_at": c.get("endsAt", ""),
                "completed_at": c.get("completedAt"),
                "progress": c.get("progress"),
                "team": c.get("team", {}).get("key", ""),
                "issue_count": len(c.get("issues", {}).get("nodes", [])),
            })
        return cycles

    # ── Projects ──

    async def list_projects(self, limit: int = 10) -> List[Dict]:
        """List projects.
        
        Args:
            limit: Max results (default 10)
        """
        query = f"""
        query {{
            projects(first: {limit}, orderBy: updatedAt) {{
                nodes {{
                    id name description state
                    progress targetDate
                    lead {{ name }}
                    teams {{ nodes {{ name key }} }}
                    createdAt updatedAt url
                }}
            }}
        }}"""
        
        data = await self._graphql(query)
        projects = []
        for p in data.get("projects", {}).get("nodes", []):
            projects.append({
                "id": p.get("id", ""),
                "name": p.get("name", ""),
                "description": p.get("description", ""),
                "state": p.get("state", ""),
                "progress": p.get("progress"),
                "target_date": p.get("targetDate"),
                "lead": p.get("lead", {}).get("name", "") if p.get("lead") else None,
                "teams": [t.get("key", "") for t in p.get("teams", {}).get("nodes", [])],
                "url": p.get("url", ""),
            })
        return projects

    # ── Me ──

    async def me(self) -> Dict:
        """Get the current authenticated user."""
        data = await self._graphql("""
        query {
            viewer {
                id name email admin
                organization { name urlKey }
                assignedIssues(first: 5) {
                    nodes { identifier title state { name } }
                }
            }
        }""")
        
        viewer = data.get("viewer", {})
        return {
            "id": viewer.get("id", ""),
            "name": viewer.get("name", ""),
            "email": viewer.get("email", ""),
            "admin": viewer.get("admin", False),
            "organization": viewer.get("organization", {}).get("name", ""),
            "recent_assigned": [{
                "identifier": i.get("identifier", ""),
                "title": i.get("title", ""),
                "status": i.get("state", {}).get("name", ""),
            } for i in viewer.get("assignedIssues", {}).get("nodes", [])],
        }

    # ── Internal Helpers ──

    def _parse_issue(self, node: Dict) -> Dict:
        """Parse an issue node into a clean dict."""
        result = {
            "id": node.get("id", ""),
            "identifier": node.get("identifier", ""),
            "title": node.get("title", ""),
            "url": node.get("url", ""),
        }
        
        if node.get("description"):
            result["description"] = node["description"][:500]
        if node.get("priority") is not None:
            result["priority"] = node.get("priorityLabel", str(node["priority"]))
        if node.get("state"):
            result["status"] = node["state"].get("name", "")
        if node.get("assignee"):
            result["assignee"] = node["assignee"].get("name", "")
        if node.get("team"):
            result["team"] = node["team"].get("key", node["team"].get("name", ""))
        if node.get("labels", {}).get("nodes"):
            result["labels"] = [l.get("name", "") for l in node["labels"]["nodes"]]
        if node.get("dueDate"):
            result["due_date"] = node["dueDate"]
        if node.get("estimate") is not None:
            result["estimate"] = node["estimate"]
        if node.get("createdAt"):
            result["created_at"] = node["createdAt"]
        if node.get("updatedAt"):
            result["updated_at"] = node["updatedAt"]
        
        return result
