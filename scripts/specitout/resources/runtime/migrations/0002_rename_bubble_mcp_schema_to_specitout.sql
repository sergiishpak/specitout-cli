-- Data-preserving runtime schema rename for the SpecItOut product-owned data schema.
-- Keep specitout_runtime reserved for migration ledger metadata.

do $$
begin
  if exists (select 1 from pg_namespace where nspname = 'bubble_mcp')
     and exists (select 1 from pg_namespace where nspname = 'specitout') then
    raise exception
      'Cannot rename legacy schema bubble_mcp to specitout because both schemas exist. Resolve the schema conflict manually before rerunning SpecItOut runtime migrations.';
  end if;

  if exists (select 1 from pg_namespace where nspname = 'bubble_mcp') then
    alter schema bubble_mcp rename to specitout;
  elsif not exists (select 1 from pg_namespace where nspname = 'specitout') then
    create schema specitout;
  end if;
end
$$;

do $$
declare
  function_row record;
  function_definition text;
begin
  for function_row in
    select p.oid
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'specitout'
    order by p.oid
  loop
    function_definition := replace(pg_get_functiondef(function_row.oid), 'bubble_mcp', 'specitout');
    execute function_definition;
  end loop;
end
$$;
