# Smart-Thinking — local MCP environment

Smart-Thinking stocke un graphe de raisonnement par session: des pensées (nœuds) ajoutées au fil des appels et des connexions typées (arêtes) entre pensées. Chaque appel API crée un nœud, peut créer/mettre à jour des liens vers des nœuds existants, et peut déclencher des artefacts dérivés (suggestions, visualisations, demandes de vérification) rattachés au même contexte de session/utilisateur.

Repository: https://github.com/Leghis/Smart-Thinking
Homepage: https://smithery.ai/server/@Leghis/smart-thinking

## Datastore

- `users.json` — Utilisateurs applicatifs identifiés par userId (personnalisation, quotas simples, multi-sessions). (12 rows; fields: ['id', 'external_user_id', 'status', 'preferences', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(external_user_id)
  - constraint: external_user_id <> ''
  - constraint: status in ('active','disabled','deleted')
- `sessions.json` — Sessions de raisonnement pour maintenir l'état entre les appels (paramètre sessionId). Contient aussi les options de fonctionnement par défaut. (12 rows; fields: ['id', 'external_session_id', 'user_id', 'status', 'default_suggest_tools', 'default_help', 'created_at', 'updated_at', 'closed_at'])
  - lifecycle `status`: ['active', 'archived', 'closed']
  - constraint: unique(external_session_id)
  - constraint: external_session_id <> ''
  - constraint: fk(user_id) references users(id) on delete set null
  - constraint: status in ('active','archived','closed')
- `thoughts.json` — Nœuds du graphe de raisonnement. Chaque appel au tool crée une pensée (thought) associée à une session (sessionId) et éventuellement à un userId. (33 rows; fields: ['id', 'session_id', 'user_id', 'content', 'thought_type', 'contains_calculations', 'request_verification', 'request_suggestions', 'suggest_tools', 'help_requested', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['created', 'enriched', 'archived', 'deleted']
  - constraint: content <> ''
  - constraint: thought_type in ('regular','revision','meta','hypothesis','conclusion')
  - constraint: fk(session_id) references sessions(id) on delete cascade
  - constraint: fk(user_id) references users(id) on delete set null
- `thought_connections.json` — Arêtes du graphe liant une pensée source (créée à l'appel) à une pensée cible existante (connections[].targetId) avec typage, force et attributs. (38 rows; fields: ['id', 'session_id', 'source_thought_id', 'target_thought_id', 'connection_type', 'strength', 'description', 'temporality', 'certainty', 'directionality', 'scope', 'nature', 'custom_attributes', 'inferred', 'inference_confidence', 'bidirectional', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded', 'deleted']
  - constraint: fk(session_id) references sessions(id) on delete cascade
  - constraint: fk(source_thought_id) references thoughts(id) on delete cascade
  - constraint: fk(target_thought_id) references thoughts(id) on delete cascade
  - constraint: source_thought_id <> target_thought_id
- `artifacts.json` — Sorties dérivées liées à une pensée: suggestions, visualisations demandées, et résultats de vérification. Représente aussi les options de visualisation (visualizationType, visualizationOptions). (19 rows; fields: ['id', 'session_id', 'thought_id', 'artifact_type', 'status', 'request_flags', 'visualization_type', 'visualization_options', 'result_payload', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['requested', 'generating', 'ready', 'failed', 'cancelled']
  - constraint: fk(session_id) references sessions(id) on delete cascade
  - constraint: fk(thought_id) references thoughts(id) on delete cascade
  - constraint: artifact_type in ('suggestions','visualization','verification','help')
  - constraint: if artifact_type='visualization' then visualization_type is not null

## Business rules enforced by the tools

- Chaque appel à l'outil smartthinking doit créer exactement une ligne thoughts avec content=thought et thought_type=thoughtType (défaut 'regular' si absent).
- Si sessionId est fourni, il est résolu vers sessions.external_session_id; si aucune session n'existe, une nouvelle session est créée avec status='active'.
- Si userId est fourni, il est résolu vers users.external_user_id; si aucun utilisateur n'existe, un utilisateur est créé avec status='active'. La session.user_id est renseignée si non déjà fixée, sinon doit correspondre (interdire le changement d'utilisateur d'une session active).
- Pour chaque élément de connections[]: créer une thought_connections ligne (ou réactiver une ligne 'superseded') avec target_thought_id=connections[].targetId, connection_type=connections[].type, strength=connections[].strength; strength doit être dans [0,1].
- Intégrité de session du graphe: source_thought.session_id == target_thought.session_id == thought_connections.session_id; sinon l'appel échoue (pas de liens cross-session).
- connections[].inferenceConfidence ne peut être non-null que si connections[].inferred=true; si inferred=false alors inference_confidence doit être null.
- Si generateVisualization=true, créer (ou remettre en 'requested') un artifacts de type 'visualization' avec visualization_type=visualizationType (défaut 'graph') et visualization_options=visualizationOptions (si fourni).
- Si requestSuggestions=true, créer (ou remettre en 'requested') un artifacts de type 'suggestions' pour la pensée.
- Si requestVerification=true ou containsCalculations=true, créer (ou remettre en 'requested') un artifacts de type 'verification' pour la pensée.
- Si help=true, produire un artifacts de type 'help' (optionnellement cacheable au niveau session) et ne pas créer de duplicat actif (unique(thought_id, 'help') en statut requested/generating/ready).
- Les transitions de statut doivent être respectées: par exemple, une connexion 'deleted' ne peut pas redevenir 'active' (uniquement via création d'une nouvelle ligne), et un artefact 'ready' ne redevient pas 'generating'.
- Limiter les tailles: content <= 20000 caractères; connections[] <= 200 par appel; visualization_options sérialisé <= 64KB; result_payload <= 1MB (sinon status='failed' avec error_message explicite).