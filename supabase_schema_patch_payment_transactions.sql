ALTER TABLE public.payment_transactions
ADD COLUMN IF NOT EXISTS transaction_id TEXT,
ADD COLUMN IF NOT EXISTS customer_name TEXT,
ADD COLUMN IF NOT EXISTS customer_email TEXT,
ADD COLUMN IF NOT EXISTS currency TEXT DEFAULT 'VND',
ADD COLUMN IF NOT EXISTS method TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_transactions_transaction_id
ON public.payment_transactions(transaction_id)
WHERE transaction_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_payment_transactions_customer_email
ON public.payment_transactions(customer_email);

CREATE INDEX IF NOT EXISTS idx_payment_transactions_method
ON public.payment_transactions(method);
