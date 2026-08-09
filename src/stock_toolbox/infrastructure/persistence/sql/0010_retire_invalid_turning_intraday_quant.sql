DELETE FROM quant_result_cache
WHERE script_version = 'turning-point-quant-v3'
  AND interval IN ('120m', '240m');
