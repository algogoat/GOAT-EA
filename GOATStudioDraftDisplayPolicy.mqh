#ifndef GOAT_STUDIO_DRAFT_DISPLAY_POLICY_MQH
#define GOAT_STUDIO_DRAFT_DISPLAY_POLICY_MQH
// Display ownership is separate from retained human editor bytes. Agent views
// mirror the accepted snapshot; only a human editor may restore or persist edits.
bool GoatStudioHumanDraftIO(const bool human_owner)
  {
   return human_owner;
  }
bool GoatStudioHydrateSnapshot(const bool agent_owner,const bool local_dirty,
                              const bool loaded,const bool version_changed)
  {
   return agent_owner || (!local_dirty && (!loaded || version_changed));
  }
#endif
