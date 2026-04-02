-- ============================================================
-- ENGLISH TEACHER BOT — PostgreSQL Database Schema v1.0
-- ============================================================
-- Compatível com PostgreSQL 14+
-- Execute com: psql -U seu_usuario -d english_bot -f 001_schema.sql
-- ============================================================

-- Garante extensão para UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- 1. TABELA: users (Alunos)
-- ============================================================
-- Cada aluno é identificado pelo número de WhatsApp.
-- Armazena dados de perfil e nível de inglês.
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone           VARCHAR(20) NOT NULL,
    name            VARCHAR(100),
    english_level   VARCHAR(2) CHECK (english_level IN ('A', 'B', 'C')),
    preferred_topic VARCHAR(200),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_users_phone UNIQUE (phone)
);

COMMENT ON TABLE users IS 'Alunos identificados pelo número de WhatsApp';
COMMENT ON COLUMN users.phone IS 'Número no formato internacional sem + (ex: 5547999999999)';
COMMENT ON COLUMN users.english_level IS 'Nível: A=Iniciante, B=Intermediário, C=Avançado';

-- ============================================================
-- 2. TABELA: user_progress (Progresso do aluno)
-- ============================================================
-- Armazena métricas de evolução do aluno ao longo do tempo.
-- Uma linha por dia (ou por sessão significativa).
-- ============================================================

CREATE TABLE IF NOT EXISTS user_progress (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    total_sessions      INT NOT NULL DEFAULT 0,
    total_messages      INT NOT NULL DEFAULT 0,
    total_audio_messages INT NOT NULL DEFAULT 0,
    total_errors_found  INT NOT NULL DEFAULT 0,
    total_errors_fixed  INT NOT NULL DEFAULT 0,
    streak_days         INT NOT NULL DEFAULT 0,
    last_practice_at    TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_user_progress UNIQUE (user_id)
);

COMMENT ON TABLE user_progress IS 'Métricas agregadas de progresso por aluno';

-- ============================================================
-- 3. TABELA: conversations (Sessões de conversa)
-- ============================================================
-- Cada vez que o aluno interage, pertence a uma conversa.
-- Uma conversa expira após o timeout configurado.
-- ============================================================

CREATE TABLE IF NOT EXISTS conversations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    state           VARCHAR(20) NOT NULL DEFAULT 'new'
                        CHECK (state IN ('new', 'waiting_name', 'waiting_level',
                                         'waiting_topic', 'chatting', 'ended')),
    topic           VARCHAR(200),
    english_level   VARCHAR(2) CHECK (english_level IN ('A', 'B', 'C')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE conversations IS 'Sessões de conversa entre aluno e bot';
COMMENT ON COLUMN conversations.state IS 'Estado da máquina de estados do fluxo de conversa';

-- ============================================================
-- 4. TABELA: messages (Mensagens individuais)
-- ============================================================
-- Cada mensagem trocada na conversa (user ou assistant).
-- Projetada para milhões de registros.
-- ============================================================

CREATE TABLE IF NOT EXISTS messages (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id     UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role                VARCHAR(10) NOT NULL CHECK (role IN ('user', 'assistant')),
    content             TEXT NOT NULL,
    message_type        VARCHAR(10) NOT NULL DEFAULT 'text'
                            CHECK (message_type IN ('text', 'audio', 'image')),
    audio_transcription TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE messages IS 'Mensagens trocadas em cada conversa';
COMMENT ON COLUMN messages.role IS 'user = aluno, assistant = bot/IA';
COMMENT ON COLUMN messages.audio_transcription IS 'Transcrição do Whisper quando a mensagem é de áudio';

-- ============================================================
-- 5. TABELA: corrections (Correções feitas pela IA)
-- ============================================================
-- Armazena o feedback de cada correção feita em uma mensagem.
-- Permite análise posterior de padrões de erros.
-- ============================================================

CREATE TABLE IF NOT EXISTS corrections (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id      UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    original_text   TEXT NOT NULL,
    corrected_text  TEXT NOT NULL,
    encouragement   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE corrections IS 'Correções aplicadas pela IA nas mensagens do aluno';

-- ============================================================
-- 6. TABELA: correction_errors (Erros individuais de cada correção)
-- ============================================================
-- Normaliza a lista de erros que antes ficava em JSON.
-- Permite queries como "quais erros o aluno mais comete?"
-- ============================================================

CREATE TABLE IF NOT EXISTS correction_errors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    correction_id   UUID NOT NULL REFERENCES corrections(id) ON DELETE CASCADE,
    wrong_text      TEXT NOT NULL,
    right_text      TEXT NOT NULL,
    rule            TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE correction_errors IS 'Erros individuais encontrados em cada correção';

-- ============================================================
-- 7. TABELA: correction_tips (Dicas de cada correção)
-- ============================================================
-- Normaliza as dicas que a IA dá ao aluno.
-- ============================================================

CREATE TABLE IF NOT EXISTS correction_tips (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    correction_id   UUID NOT NULL REFERENCES corrections(id) ON DELETE CASCADE,
    tip_text        TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE correction_tips IS 'Dicas práticas fornecidas em cada correção';

-- ============================================================
-- 8. TABELA: learning_paths (Trilhas de aprendizado — futuro)
-- ============================================================
-- Preparação para trilhas estruturadas de ensino.
-- ============================================================

CREATE TABLE IF NOT EXISTS learning_paths (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(100) NOT NULL,
    description     TEXT,
    target_level    VARCHAR(2) NOT NULL CHECK (target_level IN ('A', 'B', 'C')),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order      INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE learning_paths IS 'Trilhas de aprendizado estruturadas (feature futura)';

-- ============================================================
-- 9. TABELA: lessons (Lições dentro de trilhas — futuro)
-- ============================================================

CREATE TABLE IF NOT EXISTS lessons (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    learning_path_id    UUID NOT NULL REFERENCES learning_paths(id) ON DELETE CASCADE,
    title               VARCHAR(200) NOT NULL,
    description         TEXT,
    content             TEXT,
    sort_order          INT NOT NULL DEFAULT 0,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE lessons IS 'Lições individuais dentro de uma trilha';

-- ============================================================
-- 10. TABELA: user_lessons (Progresso do aluno em lições — futuro)
-- ============================================================

CREATE TABLE IF NOT EXISTS user_lessons (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lesson_id       UUID NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    status          VARCHAR(15) NOT NULL DEFAULT 'not_started'
                        CHECK (status IN ('not_started', 'in_progress', 'completed')),
    score           INT CHECK (score >= 0 AND score <= 100),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,

    CONSTRAINT uq_user_lesson UNIQUE (user_id, lesson_id)
);

COMMENT ON TABLE user_lessons IS 'Progresso do aluno em cada lição';


-- ============================================================
-- ÍNDICES PARA PERFORMANCE
-- ============================================================

-- Users: busca por telefone (principal lookup do bot)
CREATE INDEX IF NOT EXISTS idx_users_phone ON users (phone);

-- Conversations: buscar por user_id e por estado
CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations (user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_user_state ON conversations (user_id, state)
    WHERE state != 'ended';
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations (updated_at DESC);

-- Messages: buscar por conversa (ordem cronológica)
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages (created_at);

-- Corrections: buscar por mensagem
CREATE INDEX IF NOT EXISTS idx_corrections_message ON corrections (message_id);

-- Correction errors: buscar por correção
CREATE INDEX IF NOT EXISTS idx_correction_errors_correction ON correction_errors (correction_id);

-- Correction tips: buscar por correção
CREATE INDEX IF NOT EXISTS idx_correction_tips_correction ON correction_tips (correction_id);

-- User progress: buscar por user_id
CREATE INDEX IF NOT EXISTS idx_user_progress_user ON user_progress (user_id);

-- User lessons: buscar por user_id
CREATE INDEX IF NOT EXISTS idx_user_lessons_user ON user_lessons (user_id);
CREATE INDEX IF NOT EXISTS idx_user_lessons_lesson ON user_lessons (lesson_id);


-- ============================================================
-- FUNÇÃO: Atualizar updated_at automaticamente
-- ============================================================
-- Única trigger simples — apenas atualiza timestamp.
-- Não é lógica de negócio, é manutenção de metadados.
-- ============================================================

CREATE OR REPLACE FUNCTION fn_update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION fn_update_timestamp();

CREATE TRIGGER trg_conversations_updated
    BEFORE UPDATE ON conversations
    FOR EACH ROW EXECUTE FUNCTION fn_update_timestamp();

CREATE TRIGGER trg_user_progress_updated
    BEFORE UPDATE ON user_progress
    FOR EACH ROW EXECUTE FUNCTION fn_update_timestamp();


-- ============================================================
-- INSERTS DE TESTE
-- ============================================================

-- 1. Criar um aluno
INSERT INTO users (phone, name, english_level, preferred_topic)
VALUES ('5547999990001', 'Maria Silva', 'A', 'viagens')
ON CONFLICT (phone) DO NOTHING;

-- 2. Criar uma conversa para o aluno
INSERT INTO conversations (user_id, state, topic, english_level)
SELECT id, 'chatting', 'viagens', 'A'
FROM users WHERE phone = '5547999990001';

-- 3. Inserir mensagens na conversa
DO $$
DECLARE
    v_conv_id UUID;
    v_msg_id UUID;
    v_correction_id UUID;
BEGIN
    -- Pega a conversa criada acima
    SELECT c.id INTO v_conv_id
    FROM conversations c
    JOIN users u ON u.id = c.user_id
    WHERE u.phone = '5547999990001'
    ORDER BY c.started_at DESC
    LIMIT 1;

    IF v_conv_id IS NULL THEN
        RAISE NOTICE 'Conversa não encontrada, pulando inserts de mensagens';
        RETURN;
    END IF;

    -- Mensagem do bot (assistant)
    INSERT INTO messages (conversation_id, role, content, message_type)
    VALUES (v_conv_id, 'assistant',
            'Hello Maria! Let''s talk about travel. What''s your favorite place to visit?',
            'text');

    -- Mensagem do aluno (user) com erro
    INSERT INTO messages (conversation_id, role, content, message_type)
    VALUES (v_conv_id, 'user', 'I like go to the beach because is very beautful', 'text')
    RETURNING id INTO v_msg_id;

    -- Correção da mensagem do aluno
    INSERT INTO corrections (message_id, original_text, corrected_text, encouragement)
    VALUES (v_msg_id,
            'I like go to the beach because is very beautful',
            'I like going to the beach because it is very beautiful.',
            'Great effort! Keep practicing!')
    RETURNING id INTO v_correction_id;

    -- Erros individuais
    INSERT INTO correction_errors (correction_id, wrong_text, right_text, rule) VALUES
    (v_correction_id, 'like go', 'like going', 'Use gerund (-ing) after "like"'),
    (v_correction_id, 'because is', 'because it is', 'Subject "it" is needed before the verb'),
    (v_correction_id, 'beautful', 'beautiful', 'Spelling correction');

    -- Dica
    INSERT INTO correction_tips (correction_id, tip_text) VALUES
    (v_correction_id, 'Lembre-se: verbos como like, love, hate pedem gerúndio (-ing) depois deles.');

    -- Resposta do bot
    INSERT INTO messages (conversation_id, role, content, message_type)
    VALUES (v_conv_id, 'assistant',
            'The beach sounds wonderful! Which beach do you like the most?',
            'text');

    -- Progresso do aluno
    INSERT INTO user_progress (user_id, total_sessions, total_messages, total_errors_found)
    SELECT id, 1, 2, 3
    FROM users WHERE phone = '5547999990001'
    ON CONFLICT (user_id) DO UPDATE SET
        total_sessions = EXCLUDED.total_sessions,
        total_messages = EXCLUDED.total_messages,
        total_errors_found = EXCLUDED.total_errors_found;
END $$;


-- ============================================================
-- QUERIES ÚTEIS PARA VERIFICAÇÃO
-- ============================================================

-- Ver todos os alunos
-- SELECT * FROM users;

-- Ver conversa com mensagens
-- SELECT m.role, m.content, m.created_at
-- FROM messages m
-- JOIN conversations c ON c.id = m.conversation_id
-- JOIN users u ON u.id = c.user_id
-- WHERE u.phone = '5547999990001'
-- ORDER BY m.created_at;

-- Ver erros mais comuns (top 10 regras)
-- SELECT ce.rule, COUNT(*) as total
-- FROM correction_errors ce
-- GROUP BY ce.rule
-- ORDER BY total DESC
-- LIMIT 10;

-- Ver progresso do aluno
-- SELECT u.name, u.english_level, up.*
-- FROM user_progress up
-- JOIN users u ON u.id = up.user_id;
