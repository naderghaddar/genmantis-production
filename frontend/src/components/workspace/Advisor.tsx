import FindLeads from "./FindLeads";
import type { Campaign, Workspace } from "../../services/workspaceApi";

// Compatibility export for the former screen. All actions now use the manual search form.
export default function Advisor(props: {
  workspace: Workspace;
  refresh: () => Promise<void>;
  review: (campaign: Campaign) => void;
  researchAvailable?: boolean;
}) {
  return <FindLeads workspace={props.workspace} refresh={props.refresh} review={props.review} />;
}
