/* Query: Multi-hop Smuggling Route Tracer
   Objective: Identify hidden paths from Korea to China via intermediaries.
*/

WITH RECURSIVE supply_chain_path AS (
    -- Base Case: Shipments leaving Korea
    SELECT 
        s.origin_id,
        s.destination_id,
        n1.entity_name as start_node,
        n2.entity_name as next_node,
        1 as hop_count,
        ARRAY[n1.entity_name::text, n2.entity_name::text] as route_path
    FROM shipments s
    JOIN supply_nodes n1 ON s.origin_id = n1.node_id
    JOIN supply_nodes n2 ON s.destination_id = n2.node_id
    WHERE n1.country_code = 'KR'

    UNION ALL

    -- Recursive Step: Trace where the receiver sends it next
    SELECT 
        s.origin_id,
        s.destination_id,
        scp.next_node,
        n_next.entity_name,
        scp.hop_count + 1,
        scp.route_path || n_next.entity_name::text
    FROM shipments s
    JOIN supply_chain_path scp ON s.origin_id = scp.destination_id
    JOIN supply_nodes n_next ON s.destination_id = n_next.node_id
    WHERE scp.hop_count < 3 -- Limit recursion depth
)
SELECT route_path 
FROM supply_chain_path
WHERE route_path[array_length(route_path, 1)] LIKE '%China%';